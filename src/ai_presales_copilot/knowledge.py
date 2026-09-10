"""Small local retriever used for offline tests and the llama.cpp integration demo."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .schemas import Evidence


@dataclass(frozen=True)
class Document:
    evidence_id: str
    title: str
    path: Path
    text: str
    source_id: str | None = None
    source_url: str | None = None
    version: str = "repository-snapshot"
    license: str = "repository-synthetic"
    fetched_at: str | None = None
    tenant_id: str = "public"
    acl: tuple[str, ...] = ()
    effective_from: str | None = None
    effective_to: str | None = None
    retrieval_only: bool = True
    training_allowed: bool = False


def _terms(text: str) -> list[str]:
    """Use words plus Chinese character bigrams so no tokenizer is required."""

    normalized = re.sub(r"\s+", " ", text.lower())
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", normalized)
    bigrams = [
        normalized[i : i + 2] for i in range(len(normalized) - 1) if not normalized[i].isspace()
    ]
    return words + bigrams


class KnowledgeBase:
    """A transparent term-frequency retriever for a small portfolio corpus."""

    def __init__(self, directory: str | Path, chunks_path: str | Path | None = None):
        self.directory = Path(directory)
        self.chunks_path = Path(chunks_path) if chunks_path else None
        self.documents = self._load_chunks() if self.chunks_path and self.chunks_path.is_file() else self._load_documents()

    def _load_chunks(self) -> list[Document]:
        import json

        documents: list[Document] = []
        assert self.chunks_path is not None
        for line in self.chunks_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            source_path = payload.get("source_path") or payload.get("source_url") or "knowledge"
            documents.append(
                Document(
                    evidence_id=str(payload["evidence_id"]),
                    title=str(payload.get("title") or payload.get("source_id")),
                    path=Path(source_path),
                    text=str(payload.get("excerpt") or payload.get("text") or ""),
                    source_id=str(payload.get("source_id") or payload["evidence_id"]),
                    source_url=payload.get("source_url"),
                    version=str(payload.get("version") or "unknown"),
                    license=str(payload.get("license") or "unknown"),
                    fetched_at=payload.get("fetched_at"),
                    tenant_id=str(payload.get("tenant_id") or "public"),
                    acl=tuple(payload.get("acl") or ()),
                    effective_from=payload.get("effective_from"),
                    effective_to=payload.get("effective_to"),
                    retrieval_only=bool(payload.get("retrieval_only", True)),
                    training_allowed=bool(payload.get("training_allowed", False)),
                )
            )
        return documents

    def _load_documents(self) -> list[Document]:
        documents: list[Document] = []
        content_paths = [
            path for path in sorted(self.directory.glob("*.md")) if path.name.lower() != "readme.md"
        ]
        for index, path in enumerate(content_paths, start=1):
            text = path.read_text(encoding="utf-8")
            title = next(
                (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")),
                path.stem,
            )
            documents.append(Document(f"KB-{index:03d}", title, path, text))
        return documents

    def search(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.1,
        *,
        tenant_id: str | None = None,
        roles: Iterable[str] | None = None,
        source_ids: set[str] | None = None,
        as_of: datetime | None = None,
    ) -> list[Evidence]:
        query_terms = _terms(query)
        if not query_terms:
            return []
        query_counts = {term: query_terms.count(term) for term in set(query_terms)}
        ranked: list[tuple[float, Document]] = []
        role_set = set(roles or ())
        for document in self.documents:
            if not _document_visible(document, tenant_id=tenant_id, roles=role_set, source_ids=source_ids, as_of=as_of):
                continue
            document_terms = _terms(document.text)
            if not document_terms:
                continue
            doc_counts = {term: document_terms.count(term) for term in set(document_terms)}
            numerator = sum(
                query_counts.get(term, 0) * doc_counts.get(term, 0) for term in query_counts
            )
            query_norm = math.sqrt(sum(value * value for value in query_counts.values()))
            doc_norm = math.sqrt(sum(value * value for value in doc_counts.values()))
            score = numerator / (query_norm * doc_norm) if query_norm and doc_norm else 0.0
            if score >= min_score:
                ranked.append((score, document))
        ranked.sort(key=lambda item: item[0], reverse=True)
        results: list[Evidence] = []
        for score, document in ranked[:top_k]:
            excerpt = _excerpt(document.text, query_terms)
            try:
                source_path = str(document.path.relative_to(self.directory.parent.parent))
            except ValueError:
                source_path = str(document.path)
            results.append(
                Evidence(
                    document.evidence_id,
                    document.title,
                    excerpt,
                    source_path,
                    round(score, 4),
                    source_id=document.source_id or document.evidence_id,
                    source_url=document.source_url,
                    version=document.version,
                    license=document.license,
                    locator="document-level",
                    content_hash=_document_hash(document),
                    fetched_at=document.fetched_at,
                    effective_from=document.effective_from,
                    effective_to=document.effective_to,
                    tenant_id=document.tenant_id,
                    acl=list(document.acl),
                )
            )
        return results

    def search_hybrid(
        self,
        queries: Iterable[str],
        *,
        top_k: int = 8,
        tenant_id: str | None = None,
        roles: Iterable[str] | None = None,
        source_ids: set[str] | None = None,
    ) -> list[Evidence]:
        """Merge lexical candidates across rewritten queries.

        The local baseline keeps the unit-test path dependency-light.  The same
        method shape is shared with the PostgreSQL pgvector + tsvector
        retriever, so replacing the scorer does not change the Agent contract.
        """

        merged: dict[str, Evidence] = {}
        for query in queries:
            for item in self.search(
                query,
                top_k=top_k,
                tenant_id=tenant_id,
                roles=roles,
                source_ids=source_ids,
            ):
                previous = merged.get(item.evidence_id)
                if previous is None or item.relevance > previous.relevance:
                    merged[item.evidence_id] = item
        return sorted(merged.values(), key=lambda item: item.relevance, reverse=True)[:top_k]

    def visible_documents(
        self,
        *,
        tenant_id: str | None = None,
        roles: Iterable[str] | None = None,
        source_ids: set[str] | None = None,
    ) -> list[Document]:
        role_set = set(roles or ())
        return [
            document
            for document in self.documents
            if _document_visible(document, tenant_id=tenant_id, roles=role_set, source_ids=source_ids)
        ]

    def revoke_source(self, source_id: str, *, content_hash: str | None = None) -> int:
        """Remove an exact source/version from the in-process index."""

        before = len(self.documents)
        self.documents = [
            document
            for document in self.documents
            if not (
                (document.source_id or document.evidence_id) == source_id
                and (content_hash is None or _document_hash(document) == content_hash)
            )
        ]
        return before - len(self.documents)


def _excerpt(text: str, query_terms: list[str], width: int = 300) -> str:
    lines = [
        line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")
    ]
    if not lines:
        return text[:width]
    best = max(lines, key=lambda line: sum(line.lower().count(term) for term in query_terms))
    return best[:width]


def _document_visible(
    document: Document,
    *,
    tenant_id: str | None,
    roles: set[str],
    source_ids: set[str] | None,
    as_of: datetime | None = None,
) -> bool:
    source_id = document.source_id or document.evidence_id
    if source_ids is not None and source_id not in source_ids and document.evidence_id not in source_ids:
        return False
    if tenant_id is not None and document.tenant_id not in {"public", tenant_id}:
        return False
    if document.acl and not (roles & set(document.acl)) and "admin" not in roles:
        return False
    when = as_of or datetime.now(UTC)
    if document.effective_from and _parse_time(document.effective_from) > when:
        return False
    return not (document.effective_to and _parse_time(document.effective_to) <= when)


def _parse_time(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _document_hash(document: Document) -> str:
    try:
        return hashlib.sha256(document.path.read_bytes()).hexdigest()
    except OSError:
        return hashlib.sha256(document.text.encode("utf-8")).hexdigest()
