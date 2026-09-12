#!/usr/bin/env python3
"""Validate repository governance indexes, authority links and status vocabularies."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURE_LIFECYCLES = {"Planned", "Active", "Available", "Retired"}
FEATURE_COVERAGE = {"Covered", "Partial", "Gap", "Blocked", "N/A"}
TASK_STATUSES = {"Active", "Waiting", "Blocked"}
MEMORY_SECTIONS = ["Active Decisions", "Open Issues", "Next Steps"]
REQUIRED_FILES = [
    "AGENTS.md",
    "project_memory.md",
    "任务进展.md",
    "功能列表.md",
    "docs/architecture.md",
    "docs/security-and-governance.md",
    "docs/engineering/naming.md",
    "docs/engineering/comments.md",
    "docs/engineering/python.md",
    "docs/engineering/testing.md",
    "docs/engineering/contracts.md",
    "docs/engineering/data-and-models.md",
    "contracts/openapi/src/openapi.json",
    "contracts/openapi/dist/openapi.json",
    "data/evaluation/manifest.json",
]


def _headings(text: str) -> list[str]:
    return [match.group(2).strip() for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", text, re.MULTILINE)]


def _check_memory(errors: list[str]) -> None:
    path = ROOT / "project_memory.md"
    headings = _headings(path.read_text(encoding="utf-8"))
    expected = ["Project Memory", *MEMORY_SECTIONS]
    if headings != expected:
        errors.append(f"project_memory.md must contain only the section order {expected}, got {headings}")


def _check_indexes(errors: list[str]) -> None:
    feature_text = (ROOT / "功能列表.md").read_text(encoding="utf-8")
    feature_rows = []
    for raw_line in feature_text.splitlines():
        if not raw_line.lstrip().startswith("| `CAP-"):
            continue
        cells = [cell.strip().strip("`") for cell in raw_line.strip().strip("|").split("|")]
        if len(cells) >= 7:
            feature_rows.append((cells[0], cells[2], cells[3]))
    feature_ids: set[str] = set()
    for feature_id, lifecycle, coverage in feature_rows:
        if feature_id in feature_ids:
            errors.append(f"duplicate feature ID: {feature_id}")
        feature_ids.add(feature_id)
        if lifecycle not in FEATURE_LIFECYCLES:
            errors.append(f"unsupported feature lifecycle {lifecycle!r}: {feature_id}")
        if coverage not in FEATURE_COVERAGE:
            errors.append(f"unsupported feature coverage {coverage!r}: {feature_id}")
    if not feature_rows:
        errors.append("功能列表.md contains no CAP-* feature rows")

    task_text = (ROOT / "任务进展.md").read_text(encoding="utf-8")
    task_rows = re.findall(
        r"\|\s*`([A-Z]+-[0-9]+)`\s*\|\s*(\w+)\s*\|[^|]+\|[^|]+\|\s*\[([^]]+)\]\(([^)]+)\)",
        task_text,
    )
    task_ids: set[str] = set()
    for task_id, status, _title, link in task_rows:
        if task_id in task_ids:
            errors.append(f"duplicate task ID: {task_id}")
        task_ids.add(task_id)
        if status not in TASK_STATUSES:
            errors.append(f"unsupported task status {status!r}: {task_id}")
        _check_link(link, f"任务进展.md:{task_id}", errors)
    if not task_rows and "没有需要跨模块协调的活跃任务" not in task_text:
        errors.append("任务进展.md must list active tasks or explicitly state that none are active")


TASK_DETAIL_SECTIONS = {
    "Goal": {"Goal", "目标"},
    "Non-goals": {"Non-goals", "非目标"},
    "Scope": {"Scope", "范围"},
    "Compatibility policy": {"Compatibility policy", "兼容策略"},
    "Acceptance": {"Acceptance", "验收"},
    "Verification": {"Verification", "验证"},
    "Blockers": {"Blockers", "阻塞项"},
}


def _check_task_details(errors: list[str]) -> None:
    task_files = list((ROOT / "docs/tasks/active").glob("*.md"))
    task_files.extend((ROOT / "docs/tasks/archive").rglob("*.md"))
    task_ids: set[str] = set()
    for path in task_files:
        text = path.read_text(encoding="utf-8")
        task_id = path.stem
        if not re.fullmatch(r"[A-Z][A-Z0-9]+-[0-9]+", task_id):
            errors.append(f"task detail filename must be a stable task ID: {path.relative_to(ROOT)}")
        elif task_id in task_ids:
            errors.append(f"duplicate task detail ID: {task_id}")
        task_ids.add(task_id)
        if not re.search(r"^Owner:\s*\S.+$", text, re.MULTILINE):
            errors.append(f"task detail has no owner: {path.relative_to(ROOT)}")
        headings = _headings(text)
        missing = [
            canonical
            for canonical, accepted in TASK_DETAIL_SECTIONS.items()
            if not any(heading in accepted for heading in headings)
        ]
        if missing:
            errors.append(f"task detail missing sections {missing}: {path.relative_to(ROOT)}")
        if path.parent.name == "active":
            status_match = re.search(r"^Status:\s*(\w+)\s*$", text, re.MULTILINE)
            if not status_match or status_match.group(1) not in TASK_STATUSES:
                errors.append(f"active task has unsupported status: {path.relative_to(ROOT)}")
        elif not re.search(r"^Status:\s*Completed\s*$", text, re.MULTILINE):
            errors.append(f"archived task must be Completed: {path.relative_to(ROOT)}")


def _check_link(link: str, owner: str, errors: list[str]) -> None:
    target = link.split("#", 1)[0]
    if not target or target.startswith(("http://", "https://", "mailto:")):
        return
    if not (ROOT / target).exists():
        errors.append(f"broken repository link in {owner}: {link}")


def _check_document_links(errors: list[str]) -> None:
    markdown_files = [ROOT / "AGENTS.md", ROOT / "project_memory.md", ROOT / "任务进展.md", ROOT / "功能列表.md"]
    for directory in ("docs/features", "docs/tasks/active", "docs/tasks/archive", "docs/engineering"):
        markdown_files.extend((ROOT / directory).rglob("*.md"))
    link_pattern = re.compile(r"\[[^]]+\]\(([^)]+)\)")
    for path in markdown_files:
        if not path.exists():
            continue
        for link in link_pattern.findall(path.read_text(encoding="utf-8")):
            _check_link(link, str(path.relative_to(ROOT)), errors)


def _check_lengths(errors: list[str]) -> None:
    for relative in ("功能列表.md", "任务进展.md"):
        lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
        if len(lines) > 150:
            errors.append(f"{relative} exceeds the 150-line index limit: {len(lines)}")
    for directory in (ROOT / "docs/features", ROOT / "docs/tasks", ROOT / "docs/engineering"):
        for path in directory.rglob("*.md"):
            if len(path.read_text(encoding="utf-8").splitlines()) > 300:
                errors.append(f"governance document exceeds 300 lines: {path.relative_to(ROOT)}")
            if path.stat().st_size > 40 * 1024:
                errors.append(f"governance document exceeds 40 KB: {path.relative_to(ROOT)}")


def main() -> int:
    errors: list[str] = []
    for relative in REQUIRED_FILES:
        if not (ROOT / relative).exists():
            errors.append(f"required authority file is missing: {relative}")
    if not errors:
        _check_memory(errors)
        _check_indexes(errors)
        _check_task_details(errors)
        _check_document_links(errors)
        _check_lengths(errors)
    if errors:
        print("governance check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("governance check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
