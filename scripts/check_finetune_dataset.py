#!/usr/bin/env python3
"""Validate the generated conversational dataset and print its manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_presales_copilot.compact_contract import validate_compact_solution_dict
from ai_presales_copilot.finetuning import dataset_stats, load_conversations, sha256_file

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
    expected_prompt_version = "v2-requirements-first-compact-rag-context"
    if metadata.get("system_prompt_version") != expected_prompt_version:
        print("Manifest uses an outdated system prompt; regenerate the dataset.")
        return 3
    if target_profile != "compact" or metadata.get("target_format") != "compact_json":
        print("Manifest target_format must be compact_json; regenerate the dataset.")
        return 3
    expected_metadata = {
        "synthetic": True,
        "source": "data/demo/replays/",
        "source_version": "v2-requirements-first-replay",
        "license": "internal-synthetic",
        "sensitivity": "non-sensitive",
        "purpose": "fine-tuning-experiment",
        "created_at": "2026-09-11",
    }
    if any(metadata.get(key) != value for key, value in expected_metadata.items()):
        print("Manifest provenance metadata is incomplete or stale; regenerate the dataset.")
        return 3
    source_manifest = metadata.get("source_manifest")
    if not isinstance(source_manifest, str):
        print("Manifest source_manifest is required for provenance.")
        return 3
    source_manifest_path = (ROOT / source_manifest).resolve()
    if ROOT not in source_manifest_path.parents or not source_manifest_path.is_file():
        print("Manifest source_manifest must point inside the repository.")
        return 3
    if sha256_file(source_manifest_path) != metadata.get("source_manifest_sha256"):
        print("Manifest source manifest hash is stale; regenerate the dataset.")
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
    metadata = example.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("synthetic") is not True:
        raise ValueError(f"{split}/{example.get('id')}: synthetic provenance metadata is required")
    for key, expected in (
        ("license", "internal-synthetic"),
        ("sensitivity", "non-sensitive"),
    ):
        if metadata.get(key) != expected:
            raise ValueError(f"{split}/{example.get('id')}: invalid provenance metadata {key}")
    try:
        target = json.loads(assistant_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{split}/{example.get('id')}: assistant target is not JSON") from exc
    validate_compact_solution_dict(target)


if __name__ == "__main__":
    raise SystemExit(main())
