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
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare generated schemas with the checked-in files without writing them",
    )
    args = parser.parse_args()
    payloads = {
        "output_schema_v2.json": SolutionResponseV2.model_json_schema(),
        "draft_schema_v2.json": SolutionDraftV2.model_json_schema(),
    }
    if args.check:
        mismatches: list[str] = []
        for name, payload in payloads.items():
            target = args.output_dir / name
            if not target.exists():
                mismatches.append(f"missing {target}")
                continue
            try:
                actual = json.loads(target.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                mismatches.append(f"invalid JSON in {target}: {exc}")
                continue
            if actual != payload:
                mismatches.append(f"schema drift: {target}")
        if mismatches:
            for mismatch in mismatches:
                print(mismatch)
            return 1
        print(json.dumps({"output_dir": str(args.output_dir), "schemas": list(payloads)}, ensure_ascii=False))
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (args.output_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({"output_dir": str(args.output_dir), "schemas": list(payloads)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
