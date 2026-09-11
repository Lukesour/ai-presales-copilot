#!/usr/bin/env python3
"""Start the versioned local-model FastAPI service."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from ai_presales_copilot.api_v2 import LocalTokenAuth, create_fastapi_app
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.llama_client import LlamaClient
from ai_presales_copilot.llm_agent import LocalModelWorkflow
from ai_presales_copilot.persistence import create_checkpoint_store

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--db", default=os.getenv("CHECKPOINT_DB", str(ROOT / ".runtime/agent/checkpoints.db")))
    parser.add_argument("--llama-url", default=os.getenv("LLAMA_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--model", default=os.getenv("LLAMA_MODEL", "qwen3-8b-q4"))
    parser.add_argument("--model-path", default=os.getenv("LLAMA_MODEL_PATH", ""))
    parser.add_argument("--allow-dev-auth", action="store_true")
    args = parser.parse_args()

    if args.allow_dev_auth:
        os.environ["PRESALES_ALLOW_DEV_AUTH"] = "true"

    knowledge = KnowledgeBase(
        ROOT / "data/knowledge",
        chunks_path=os.getenv("KNOWLEDGE_CHUNKS") or None,
    )
    model_hash = _verified_model_hash(args.model_path)
    store = create_checkpoint_store(args.db)
    model = LlamaClient(
        args.llama_url,
        args.model,
        timeout_s=float(os.getenv("LLAMA_TIMEOUT_S", "120")),
    )
    knowledge_index = None
    if str(args.db).startswith(("postgres://", "postgresql://")):
        from ai_presales_copilot.knowledge_store import PostgresKnowledgeIndex

        knowledge_index = PostgresKnowledgeIndex(str(args.db))
    workflow = LocalModelWorkflow(
        model,
        knowledge,
        store,
        model_hash=model_hash,
        knowledge_index=knowledge_index,
        graph_checkpointer=getattr(store, "native_graph_checkpointer", None),
    )
    app = create_fastapi_app(
        workflow,
        store,
        knowledge,
        auth=LocalTokenAuth(),
        knowledge_index=knowledge_index,
    )
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("Install runtime dependencies: python3 -m pip install -e '.[runtime]'") from exc
    print(f"Presales API listening on http://{args.host}:{args.port}")
    print("Model calls are local-only; missing/invalid model output becomes model_unavailable.")
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        if knowledge_index is not None:
            knowledge_index.close()
        store.close()
    return 0


def _sha256_if_file(value: str) -> str | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_model_hash(model_path: str) -> str | None:
    """Return the model digest and fail closed when a configured hash differs."""

    expected = os.getenv("LLAMA_MODEL_SHA256", "").strip().lower() or None
    if model_path and not Path(model_path).is_file():
        raise SystemExit(f"LLAMA_MODEL_PATH does not exist: {model_path}")
    actual = _sha256_if_file(model_path)
    if expected and actual and expected != actual.lower():
        raise SystemExit(
            "LLAMA_MODEL_SHA256 does not match LLAMA_MODEL_PATH: "
            f"expected {expected}, actual {actual}"
        )
    return actual or expected


if __name__ == "__main__":
    raise SystemExit(main())
