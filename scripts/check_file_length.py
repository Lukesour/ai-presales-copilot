#!/usr/bin/env python3
"""Report the 300-line ratchet without blocking the initial migration."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("src", "scripts", "tests", "demo", "migrations", "docs", "contracts/openapi/src")
EXCLUDED_NAMES = {"uv.lock"}
EXTENSIONS = {".py", ".md", ".sql", ".json"}


def _candidate_files() -> list[Path]:
    paths: list[Path] = []
    for root_name in SOURCE_ROOTS:
        root = ROOT / root_name
        if root.exists():
            paths.extend(path for path in root.rglob("*") if path.is_file() and path.suffix in EXTENSIONS)
    return sorted(path for path in paths if path.name not in EXCLUDED_NAMES and ".git" not in path.parts)


def _untracked() -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.splitlines())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block-new", action="store_true", help="fail only for new files over 300 lines")
    args = parser.parse_args()
    untracked = _untracked()
    oversized: list[tuple[str, int, bool]] = []
    for path in _candidate_files():
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > 300:
            relative = str(path.relative_to(ROOT))
            oversized.append((relative, lines, relative in untracked))
    if oversized:
        print("file-length report (initial rollout is report-only):")
        for relative, lines, is_new in oversized:
            marker = "new" if is_new else "existing"
            print(f"- {relative}: {lines} lines ({marker})")
    else:
        print("file-length report: no oversized candidate files")
    if args.block_new and any(is_new for _, _, is_new in oversized):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
