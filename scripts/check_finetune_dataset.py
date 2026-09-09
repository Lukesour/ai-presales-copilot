#!/usr/bin/env python3
"""Validate the generated conversational dataset and print its manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_presales_copilot.compact_contract import validate_compact_solution_dict
from ai_presales_copilot.finetuning import dataset_stats, load_conversations, sha256_file
from ai_presales_copilot.schemas import validate_solution_dict

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "data/finetuning")
    args = parser.parse_args()

    manifest = args.directory / "manifest.json"
    if not manifest.exists():
        print(f"Missing {manifest}; regenerate the dataset to keep hashes and stats traceable.")
        return 2
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    metadata = manifest_payload.get("metadata", {})
    target_profile = metadata.get("target_profile", "full")
    if target_profile not in {"full", "compact"}:
        print(f"Unsupported target_profile in manifest: {target_profile!r}")
        return 3

    rows: dict[str, object] = {}
    split_paths: dict[str, Path] = {}
    for split in ("train", "dev", "test"):
        path = args.directory / f"{split}.jsonl"
        if not path.exists():
            print(f"Missing {path}; run make build-finetune-dataset first.")
            return 2
        examples = load_conversations(path)
        rows[split] = dataset_stats(examples)
        split_paths[split] = path
        for example in examples:
            _validate_training_contract(example, split, target_profile)
    expected_prompt_version = (
        "v2-json-contract-rag-context"
        if target_profile == "full"
        else "v1-compact-decision-contract-rag-context"
    )
    if metadata.get("system_prompt_version") != expected_prompt_version:
        print("Manifest uses an outdated system prompt; regenerate the dataset.")
        return 3
    if metadata.get("target_format") != "compact_json":
        print("Manifest target_format must be compact_json; regenerate the dataset.")
        return 3
    for split, path in split_paths.items():
        entry = manifest_payload.get("files", {}).get(split)
        if not isinstance(entry, dict):
            print(f"Manifest entry missing for {split}.")
            return 3
        expected_path = (args.directory / entry["path"]).resolve()
        if not expected_path.is_relative_to(args.directory.resolve()) or expected_path != path.resolve():
            print(f"Manifest path mismatch for {split}: {entry['path']}")
            return 3
        actual_hash = sha256_file(path)
        if actual_hash != entry.get("sha256"):
            print(f"Manifest hash mismatch for {split}: expected {entry.get('sha256')}, got {actual_hash}")
            return 3
        expected_examples = manifest_payload.get("metadata", {}).get("stats", {}).get(split, {}).get("examples")
        if expected_examples != rows[split]["examples"]:
            print(f"Manifest example count mismatch for {split}.")
            return 3
    dataset_info = args.directory / "llamafactory/dataset_info.json"
    if not dataset_info.exists():
        print(f"Missing {dataset_info}; LLaMA Factory import metadata is incomplete.")
        return 3
    rows["manifest"] = manifest_payload
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def _validate_training_contract(
    example: dict[str, object], split: str, target_profile: str = "full"
) -> None:
    """Fail before training if targets or RAG context silently drift."""

    messages = example["messages"]
    if not isinstance(messages, list) or len(messages) < 3:
        raise ValueError(f"{split}/{example.get('id')}: expected system/user/assistant messages")
    user_content = messages[-2].get("content") if isinstance(messages[-2], dict) else ""
    assistant_content = messages[-1].get("content") if isinstance(messages[-1], dict) else ""
    if not isinstance(user_content, str) or '"retrieved_evidence"' not in user_content:
        raise ValueError(
            f"{split}/{example.get('id')}: user message is missing structured retrieved_evidence context"
        )
    if not isinstance(assistant_content, str):
        raise TypeError(f"{split}/{example.get('id')}: assistant target must be text")
    try:
        target = json.loads(assistant_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{split}/{example.get('id')}: assistant target is not JSON") from exc
    if target_profile == "compact":
        validate_compact_solution_dict(target)
    else:
        validate_solution_dict(target, require_all_fields=True)


if __name__ == "__main__":
    raise SystemExit(main())
