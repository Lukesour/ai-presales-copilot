#!/usr/bin/env python3
"""Start the local Agent HTTP API."""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_presales_copilot.agent import PresalesAgent
from ai_presales_copilot.api import AgentHTTPService, create_server
from ai_presales_copilot.knowledge import KnowledgeBase
from ai_presales_copilot.persistence import CheckpointStore

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--db", type=Path, default=ROOT / ".runtime/agent/checkpoints.db")
    args = parser.parse_args()

    with CheckpointStore(args.db) as store:
        service = AgentHTTPService(PresalesAgent(KnowledgeBase(ROOT / "data/knowledge"), store))
        server = create_server(args.host, args.port, service)
        print(f"Agent API listening on http://{args.host}:{args.port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping Agent API")
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
