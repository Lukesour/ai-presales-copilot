"""Dataset contracts and manifests for reproducible SFT/LoRA experiments."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ALLOWED_ROLES = {"system", "user", "assistant"}


def load_conversations(path: str | Path) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number} is not valid JSON") from exc
        validate_conversation(item, source=f"{path}:{line_number}")
        examples.append(item)
    return examples


def validate_conversation(item: dict[str, Any], source: str = "example") -> None:
    if not isinstance(item, dict):
        raise TypeError(f"{source} must be an object")
    messages = item.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        raise ValueError(f"{source}.messages must contain at least two messages")
    roles: list[str] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise TypeError(f"{source}.messages[{index}] must be an object")
        role = message.get("role")
        content = message.get("content")
        if role not in ALLOWED_ROLES:
            raise ValueError(f"{source}.messages[{index}].role is unsupported")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"{source}.messages[{index}].content must be non-empty")
        roles.append(role)
    if roles[-1] != "assistant":
        raise ValueError(f"{source} must end with an assistant message")
    if "id" in item and (not isinstance(item["id"], str) or not item["id"].strip()):
        raise ValueError(f"{source}.id must be a non-empty string")


def dataset_stats(examples: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(examples)
    role_counts: Counter[str] = Counter()
    lengths: list[int] = []
    for item in rows:
        for message in item["messages"]:
            role_counts[message["role"]] += 1
            lengths.append(len(message["content"]))
    return {
        "examples": len(rows),
        "messages": sum(role_counts.values()),
        "role_counts": dict(role_counts),
        "min_chars": min(lengths) if lengths else 0,
        "max_chars": max(lengths) if lengths else 0,
        "avg_chars": round(sum(lengths) / len(lengths), 2) if lengths else 0.0,
        "ids_unique": len({item.get("id") for item in rows}) == len(rows)
        if all("id" in item for item in rows)
        else None,
    }


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(
    output: str | Path,
    *,
    files: dict[str, str | Path],
    metadata: dict[str, Any],
) -> None:
    target = Path(output)
    base_directory = target.parent
    manifest = {
        "files": {
            name: {
                "path": str(Path(path).relative_to(base_directory))
                if Path(path).is_relative_to(base_directory)
                else str(path),
                "sha256": sha256_file(path),
            }
            for name, path in files.items()
        },
        "metadata": metadata,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
