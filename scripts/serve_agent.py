#!/usr/bin/env python3
"""Start the local-model FastAPI service (or the legacy demo explicitly)."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from ai_presales_copilot.agent import PresalesAgent
from ai_presales_copilot.api import AgentHTTPService, create_server
from ai_presales_copilot.api_v2 import LocalTokenAuth, create_fastapi_app
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.llama_client import LlamaClient
from ai_presales_copilot.llm_agent import LocalModelWorkflow
from ai_presales_copilot.persistence import CheckpointStore, create_checkpoint_store

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument(
        "--mode", choices=("local-model", "legacy"), default="local-model",
        help="local-model is the v2 API; legacy keeps the original deterministic fixture",
    )
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
    if args.mode == "legacy":
        with CheckpointStore(args.db) as store:
            service = AgentHTTPService(PresalesAgent(knowledge, store))
            server = create_server(args.host, args.port, service)
            print(f"Legacy Agent API listening on http://{args.host}:{args.port}")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nStopping Agent API")
            finally:
                server.server_close()
        return 0

    store = create_checkpoint_store(args.db)
    model = LlamaClient(
        args.llama_url,
        args.model,
        timeout_s=float(os.getenv("LLAMA_TIMEOUT_S", "120")),
    )
    model_hash = os.getenv("LLAMA_MODEL_SHA256") or _sha256_if_file(args.model_path)
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


if __name__ == "__main__":
    raise SystemExit(main())
