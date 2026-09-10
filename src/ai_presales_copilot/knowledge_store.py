"""PostgreSQL/pgvector persistence for ingested knowledge chunks.

The local SQLite/Markdown retriever remains useful for unit tests.  Compose
can additionally use this store for durable source metadata, full-text search,
optional embeddings, and source revocation.  Embeddings are nullable so the
Phase 1 stack does not silently download a second model.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable

from .ingestion import ChunkRecord, IngestedSource
from .schemas import Evidence


class PostgresKnowledgeIndex:
    def __init__(self, dsn: str, *, embedding_dimensions: int = 384):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - runtime extra only
            raise RuntimeError("Install the runtime extra to use PostgreSQL knowledge indexing") from exc
        self.connection = psycopg.connect(dsn, autocommit=True, connect_timeout=10)
        self.embedding_dimensions = embedding_dimensions
        self._lock = threading.RLock()
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._lock, self.connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    source_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    source_url TEXT,
                    source_path TEXT,
                    title TEXT NOT NULL,
                    license TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    acl JSONB NOT NULL DEFAULT '[]'::jsonb,
                    content_hash TEXT NOT NULL,
                    fetched_at TIMESTAMPTZ NOT NULL,
                    effective_from TIMESTAMPTZ,
                    effective_to TIMESTAMPTZ,
                    retrieval_only BOOLEAN NOT NULL DEFAULT TRUE,
                    training_allowed BOOLEAN NOT NULL DEFAULT FALSE,
                    revoked_at TIMESTAMPTZ,
                    PRIMARY KEY (source_id, version)
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    evidence_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    title TEXT NOT NULL,
                    excerpt TEXT NOT NULL,
                    page INTEGER,
                    locator TEXT,
                    content_hash TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    acl JSONB NOT NULL DEFAULT '[]'::jsonb,
                    training_allowed BOOLEAN NOT NULL DEFAULT FALSE,
                    embedding vector({self.embedding_dimensions}),
                    search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', excerpt)) STORED
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS knowledge_chunks_search_idx ON knowledge_chunks USING GIN(search_vector)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS knowledge_chunks_scope_idx ON knowledge_chunks(tenant_id, source_id)"
            )

    def upsert_source(self, source: IngestedSource) -> None:
        spec = source.spec
        with self._lock, self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO knowledge_sources(
                    source_id, version, source_url, source_path, title, license,
                    tenant_id, acl, content_hash, fetched_at, effective_from,
                    effective_to, retrieval_only, training_allowed, revoked_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s,
                          %s, %s, %s, %s, NULL)
                ON CONFLICT(source_id, version) DO UPDATE SET
                    source_url=excluded.source_url,
                    source_path=excluded.source_path,
                    title=excluded.title,
                    license=excluded.license,
                    tenant_id=excluded.tenant_id,
                    acl=excluded.acl,
                    content_hash=excluded.content_hash,
                    fetched_at=excluded.fetched_at,
                    effective_from=excluded.effective_from,
                    effective_to=excluded.effective_to,
                    retrieval_only=excluded.retrieval_only,
                    training_allowed=excluded.training_allowed,
                    revoked_at=NULL
                """,
                (
                    spec.source_id,
                    spec.version or source.content_hash[:16],
                    spec.source_url,
                    spec.local_path,
                    spec.title,
                    spec.license,
                    spec.tenant_id,
                    json.dumps(list(spec.acl)),
                    source.content_hash,
                    source.fetched_at,
                    spec.effective_from,
                    spec.effective_to,
                    spec.retrieval_only,
                    spec.training_allowed,
                ),
            )

    def upsert_chunks(self, chunks: Iterable[ChunkRecord], embeddings: dict[str, list[float]] | None = None) -> None:
        embeddings = embeddings or {}
        with self._lock, self.connection.cursor() as cursor:
            for chunk in chunks:
                embedding = embeddings.get(chunk.evidence_id)
                cursor.execute(
                    """
                    INSERT INTO knowledge_chunks(
                        evidence_id, source_id, version, title, excerpt, page,
                        locator, content_hash, tenant_id, acl, training_allowed, embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT(evidence_id) DO UPDATE SET
                        excerpt=excluded.excerpt,
                        page=excluded.page,
                        locator=excluded.locator,
                        content_hash=excluded.content_hash,
                        tenant_id=excluded.tenant_id,
                        acl=excluded.acl,
                        training_allowed=excluded.training_allowed,
                        embedding=excluded.embedding
                    """,
                    (
                        chunk.evidence_id,
                        chunk.source_id,
                        chunk.version,
                        chunk.title,
                        chunk.text,
                        chunk.page,
                        chunk.to_dict().get("locator"),
                        chunk.content_hash,
                        chunk.tenant_id,
                        json.dumps(list(chunk.acl)),
                        chunk.training_allowed,
                        embedding,
                    ),
                )

    def revoke_source(self, source_id: str, *, content_hash: str | None = None) -> None:
        with self._lock, self.connection.cursor() as cursor:
            if content_hash:
                cursor.execute(
                    "UPDATE knowledge_sources SET revoked_at=now() WHERE source_id=%s AND content_hash=%s",
                    (source_id, content_hash),
                )
                cursor.execute(
                    "DELETE FROM knowledge_chunks WHERE source_id=%s AND content_hash=%s",
                    (source_id, content_hash),
                )
            else:
                cursor.execute("UPDATE knowledge_sources SET revoked_at=now() WHERE source_id=%s", (source_id,))
                cursor.execute("DELETE FROM knowledge_chunks WHERE source_id=%s", (source_id,))

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        tenant_id: str | None = None,
        roles: Iterable[str] = (),
        source_ids: set[str] | None = None,
    ) -> list[Evidence]:
        """Search the durable index with scope filters applied in SQL.

        The Compose baseline uses PostgreSQL's ``simple`` tsvector index. A
        future embedding worker can add a vector score without changing the
        returned Evidence contract. ACL and revocation predicates happen
        before rows are returned, so protected text never reaches the model.
        """

        normalized_query = " ".join(str(query).split())
        if not normalized_query:
            return []
        limit = max(1, min(int(top_k), 100))
        role_list = tuple(sorted(set(roles)))
        is_admin = "admin" in role_list
        conditions = [
            "ks.revoked_at IS NULL",
            "(ks.effective_from IS NULL OR ks.effective_from <= now())",
            "(ks.effective_to IS NULL OR ks.effective_to > now())",
            "(kc.search_vector @@ plainto_tsquery('simple', %s) OR kc.excerpt ILIKE %s)",
        ]
        params: list[object] = [normalized_query, f"%{normalized_query}%"]
        if tenant_id:
            conditions.append("kc.tenant_id IN ('public', %s)")
            params.append(tenant_id)
        if source_ids is not None:
            if not source_ids:
                return []
            placeholders = ", ".join("%s" for _ in source_ids)
            conditions.append(f"kc.source_id IN ({placeholders})")
            params.extend(sorted(source_ids))
        if not is_admin:
            if role_list:
                conditions.append(
                    "(kc.acl = '[]'::jsonb OR EXISTS ("
                    "SELECT 1 FROM jsonb_array_elements_text(kc.acl) AS allowed(role) "
                    "WHERE allowed.role = ANY(%s::text[])" "))"
                )
                params.append(list(role_list))
            else:
                conditions.append("kc.acl = '[]'::jsonb")

        sql = f"""
            SELECT kc.evidence_id, kc.source_id, kc.version, kc.title, kc.excerpt,
                   kc.page, kc.locator, kc.content_hash, kc.tenant_id, kc.acl,
                   ks.source_url, ks.source_path, ks.license,
                   ks.fetched_at, ks.effective_from, ks.effective_to,
                   GREATEST(ts_rank(kc.search_vector, plainto_tsquery('simple', %s)), 0.01)
            FROM knowledge_chunks AS kc
            JOIN knowledge_sources AS ks
              ON ks.source_id = kc.source_id AND ks.version = kc.version
            WHERE {' AND '.join(conditions)}
            ORDER BY ts_rank(kc.search_vector, plainto_tsquery('simple', %s)) DESC,
                     kc.evidence_id
            LIMIT %s
        """
        # The query is used for rank expression twice, then the result limit.
        params = [normalized_query, *params, normalized_query, limit]
        with self._lock, self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        return [
            Evidence(
                evidence_id=row[0],
                title=row[3],
                excerpt=row[4],
                source_path=row[11] or "knowledge",
                relevance=min(1.0, float(row[16] or 0.01)),
                source_id=row[1],
                source_url=row[10],
                version=row[2],
                license=row[12],
                page=row[5],
                locator=row[6],
                content_hash=row[7],
                fetched_at=_iso_value(row[13]),
                effective_from=_iso_value(row[14]),
                effective_to=_iso_value(row[15]),
                tenant_id=row[8],
                acl=list(row[9] or []),
            )
            for row in rows
        ]

    def health(self) -> bool:
        with self._lock, self.connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname='vector'")
            return cursor.fetchone() is not None

    def close(self) -> None:
        with self._lock:
            self.connection.close()


def _iso_value(value: object) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
