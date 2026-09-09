#!/usr/bin/env python3
"""Audit chat-template lengths before an SFT/QLoRA run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ai_presales_copilot.finetuning import load_conversations

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--directory", type=Path, default=ROOT / "data/finetuning")
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 1 if any complete conversation exceeds --max-length.",
    )
    args = parser.parse_args()
    if args.max_length < 1:
        raise ValueError("--max-length must be positive")

    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        print(f"Tokenizer audit requires the finetune extra: {exc}")
        return 3

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    report: dict[str, Any] = {
        "model": args.model,
        "max_length": args.max_length,
        "splits": {},
    }
    has_overflow = False
    for split in ("train", "dev", "test"):
        path = args.directory / f"{split}.jsonl"
        examples = load_conversations(path)
        lengths = []
        for row in examples:
            full = tokenizer.apply_chat_template(
                row["messages"],
                tokenize=True,
                add_generation_prompt=False,
            )
            lengths.append(len(full))
        stats = _summarize(lengths, args.max_length)
        report["splits"][split] = stats
        has_overflow = has_overflow or bool(stats["over_max_length"])

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.strict and has_overflow:
        print(
            "Token audit failed: increase max_length or compact the supervised target before training."
        )
        return 1
    return 0


def _summarize(lengths: list[int], max_length: int) -> dict[str, Any]:
    if not lengths:
        return {
            "examples": 0,
            "min": 0,
            "p50": 0,
            "p90": 0,
            "max": 0,
            "over_max_length": 0,
            "over_max_length_rate": 0.0,
        }
    ordered = sorted(lengths)

    def percentile(fraction: float) -> int:
        index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
        return ordered[index]

    over = sum(length > max_length for length in ordered)
    return {
        "examples": len(ordered),
        "min": ordered[0],
        "p50": percentile(0.50),
        "p90": percentile(0.90),
        "max": ordered[-1],
        "over_max_length": over,
        "over_max_length_rate": round(over / len(ordered), 4),
    }


if __name__ == "__main__":
    raise SystemExit(main())
