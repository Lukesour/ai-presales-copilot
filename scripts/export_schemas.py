#!/usr/bin/env python3
"""Export the single Pydantic v2 contract used by API, Dify and llama-server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_presales_copilot.schemas import SolutionDraftV2, SolutionResponseV2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("dify"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "output_schema_v2.json": SolutionResponseV2.model_json_schema(),
        "draft_schema_v2.json": SolutionDraftV2.model_json_schema(),
    }
    for name, payload in payloads.items():
        (args.output_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({"output_dir": str(args.output_dir), "schemas": list(payloads)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
