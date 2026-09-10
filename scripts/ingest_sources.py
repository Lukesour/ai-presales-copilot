#!/usr/bin/env python3
"""Ingest registered local/authorized sources into chunk and manifest JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_presales_copilot.ingestion import SourceRegistry, ingest_source, write_jsonl

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "data/knowledge/source_registry.json")
    parser.add_argument("--source-id", action="append", dest="source_ids")
    parser.add_argument("--chunks", type=Path, default=ROOT / ".runtime/knowledge/chunks.jsonl")
    parser.add_argument("--manifest", type=Path, default=ROOT / ".runtime/knowledge/manifest.jsonl")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--postgres-dsn", default=None, help="also persist source/chunks into PostgreSQL + pgvector")
    parser.add_argument("--allow-sensitive", action="store_true", help="quarantine override for reviewed sources")
    args = parser.parse_args()

    registry = SourceRegistry.from_json(args.registry)
    wanted = set(args.source_ids or [])
    specs = [item for item in registry.all() if not wanted or item.source_id in wanted]
    if wanted and len(specs) != len(wanted):
        unknown = sorted(wanted - {item.source_id for item in specs})
        raise SystemExit(f"unknown source id(s): {', '.join(unknown)}")
    ingested = []
    index = None
    if args.postgres_dsn:
        from ai_presales_copilot.knowledge_store import PostgresKnowledgeIndex

        index = PostgresKnowledgeIndex(args.postgres_dsn)
    for spec in specs:
        source = ingest_source(spec, root=args.root, allow_sensitive=args.allow_sensitive)
        ingested.append(source)
        if index is not None:
            index.upsert_source(source)
            index.upsert_chunks(source.chunks)
        print(json.dumps(source.manifest(), ensure_ascii=False))
    write_jsonl(ingested, args.chunks, args.manifest)
    if index is not None:
        index.close()
    print(json.dumps({"sources": len(ingested), "chunks": sum(len(item.chunks) for item in ingested)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
