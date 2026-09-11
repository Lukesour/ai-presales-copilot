#!/usr/bin/env python3
"""Revoke an exact knowledge source/version from PostgreSQL and JSONL mirrors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_presales_copilot.knowledge_store import PostgresKnowledgeIndex


def _matches(payload: dict, source_id: str, content_hash: str | None) -> bool:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else payload
    if str(source.get("source_id", "")) != source_id:
        return False
    return content_hash is None or str(
        payload.get("source_content_hash") or payload.get("content_hash") or source.get("content_hash", "")
    ) == content_hash


def _revoke_jsonl(path: Path, source_id: str, content_hash: str | None) -> int:
    if not path.is_file():
        return 0
    kept: list[str] = []
    removed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if _matches(payload, source_id, content_hash):
            removed += 1
        else:
            kept.append(json.dumps(payload, ensure_ascii=False))
    if removed:
        temporary = path.with_name(path.name + ".revoke.tmp")
        temporary.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        temporary.replace(path)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--content-hash")
    parser.add_argument("--postgres-dsn")
    parser.add_argument("--chunks", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if not any((args.postgres_dsn, args.chunks, args.manifest)):
        parser.error("at least one of --postgres-dsn, --chunks, or --manifest is required")

    result: dict[str, int] = {}
    if args.postgres_dsn:
        index = PostgresKnowledgeIndex(args.postgres_dsn)
        try:
            index.revoke_source(args.source_id, content_hash=args.content_hash)
            result["postgres"] = 1
        finally:
            index.close()
    if args.chunks:
        result["chunks"] = _revoke_jsonl(args.chunks, args.source_id, args.content_hash)
    if args.manifest:
        result["manifest"] = _revoke_jsonl(args.manifest, args.source_id, args.content_hash)
    print(json.dumps({"source_id": args.source_id, "content_hash": args.content_hash, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
