"""Validate provenance and hashes for the current requirements-first replay dataset."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data/evaluation/manifest.json"
EXPECTED_SCENARIOS = {"normal", "high_risk", "missing_then_clarified", "conflict_or_injection"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path(payload: dict[str, Any], key: str) -> Path:
    relative = payload[key]["path"]
    target = (ROOT / relative).resolve()
    if ROOT not in target.parents:
        raise ValueError(f"manifest path escapes repository: {relative}")
    return target


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    metadata = manifest.get("metadata", {})
    expected_metadata = {
        "synthetic": True,
        "source_version": "demo-catalog-1.0/replay-1.0",
        "license": "internal-synthetic",
        "sensitivity": "non-sensitive",
        "purpose": "offline-evaluation",
        "created_at": "2026-09-11",
    }
    if metadata != expected_metadata:
        raise ValueError(f"unexpected replay dataset metadata: {metadata}")

    source = manifest["source"]
    catalog = _path(source, "scenario_catalog")
    if _sha256(catalog) != source["scenario_catalog"]["sha256"]:
        raise ValueError("scenario catalog hash does not match manifest")
    replays = source["replays"]
    if set(replays) != EXPECTED_SCENARIOS:
        raise ValueError("replay manifest does not cover the registered scenarios")
    for scenario_id, record in replays.items():
        replay_path = _path(replays, scenario_id)
        if _sha256(replay_path) != record["sha256"]:
            raise ValueError(f"replay hash does not match manifest: {scenario_id}")

    cases = manifest["files"]["cases"]
    cases_path = _path(manifest["files"], "cases")
    if _sha256(cases_path) != cases["sha256"]:
        raise ValueError("replay cases hash does not match manifest")
    case_ids: set[str] = set()
    with cases_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            record = json.loads(line)
            case_id = record.get("case_id")
            scenario_id = record.get("expected", {}).get("scenario_id")
            if not isinstance(case_id, str) or not isinstance(scenario_id, str):
                raise TypeError(f"invalid replay case metadata at line {line_number}")
            if case_id in case_ids:
                raise ValueError(f"duplicate replay case: {case_id}")
            case_ids.add(case_id)
            if scenario_id not in EXPECTED_SCENARIOS:
                raise ValueError(f"unknown replay scenario at line {line_number}: {scenario_id}")
    if len(case_ids) != len(EXPECTED_SCENARIOS):
        raise ValueError("replay case index must contain one case per registered scenario")
    print(f"replay manifest passed: {len(case_ids)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
