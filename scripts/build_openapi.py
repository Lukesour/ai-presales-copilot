#!/usr/bin/env python3
"""Resolve the hand-written OpenAPI fragments into the generated bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "contracts" / "openapi" / "src"
DIST_PATH = REPOSITORY_ROOT / "contracts" / "openapi" / "dist" / "openapi.json"


class OpenAPIReferenceError(ValueError):
    """Raised when an OpenAPI fragment contains an invalid local reference."""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise OpenAPIReferenceError(f"OpenAPI fragment does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAPIReferenceError(f"invalid JSON in {path}: {exc}") from exc


def _pointer(document: Any, fragment: str, source: Path) -> Any:
    if not fragment:
        return document
    if not fragment.startswith("/"):
        raise OpenAPIReferenceError(f"unsupported JSON pointer '#{fragment}' in {source}")
    current = document
    for raw_token in fragment[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        try:
            current = current[int(token)] if isinstance(current, list) else current[token]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise OpenAPIReferenceError(f"missing reference '#{fragment}' in {source}") from exc
    return current


def _resolve_reference(reference: str, base_path: Path, stack: tuple[str, ...]) -> Any:
    target_name, _separator, fragment = reference.partition("#")
    if target_name:
        target_path = (base_path.parent / target_name).resolve()
    else:
        target_path = base_path.resolve()
    target_key = f"{target_path}#{fragment}"
    if target_key in stack:
        raise OpenAPIReferenceError(f"cyclic OpenAPI reference: {' -> '.join((*stack, target_key))}")
    document = _load_json(target_path)
    selected = _pointer(document, fragment, target_path)
    return _resolve_node(selected, target_path, (*stack, target_key))


def _resolve_node(value: Any, base_path: Path, stack: tuple[str, ...] = ()) -> Any:
    if isinstance(value, list):
        return [_resolve_node(item, base_path, stack) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        reference = value["$ref"]
        if not isinstance(reference, str):
            raise OpenAPIReferenceError(f"$ref must be a string in {base_path}")
        resolved = _resolve_reference(reference, base_path, stack)
        siblings = {key: item for key, item in value.items() if key != "$ref"}
        if not siblings:
            return resolved
        if not isinstance(resolved, dict):
            raise OpenAPIReferenceError(f"$ref siblings require an object target in {base_path}")
        merged = dict(resolved)
        merged.update(siblings)
        return _resolve_node(merged, base_path, stack)
    return {key: _resolve_node(item, base_path, stack) for key, item in value.items()}


def build_bundle() -> dict[str, Any]:
    """Return the fully resolved OpenAPI document."""

    return _resolve_node(_load_json(SOURCE_ROOT / "openapi.json"), SOURCE_ROOT / "openapi.json")


def _serialized(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the generated bundle differs from contracts/openapi/dist/openapi.json",
    )
    args = parser.parse_args()
    try:
        bundle = build_bundle()
    except OpenAPIReferenceError as exc:
        print(f"openapi build failed: {exc}", file=sys.stderr)
        return 1

    rendered = _serialized(bundle)
    if args.check:
        if not DIST_PATH.exists() or DIST_PATH.read_text(encoding="utf-8") != rendered:
            print(f"generated OpenAPI bundle is stale: {DIST_PATH}", file=sys.stderr)
            return 1
        print(f"OpenAPI bundle is up to date: {DIST_PATH}")
        return 0

    DIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIST_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {DIST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
