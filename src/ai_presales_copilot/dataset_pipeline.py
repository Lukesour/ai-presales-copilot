"""Self-Instruct/Self-QA candidate filtering and provenance manifests."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schemas import SolutionResponseV2, validate_solution_dict
from .security import inspect_sensitive_data, inspect_untrusted_input


@dataclass(frozen=True)
class CandidateDecision:
    record_id: str
    accepted: bool
    reasons: tuple[str, ...] = ()
    fingerprint: str = ""
    source_group: str = ""
    split: str = ""


@dataclass(frozen=True)
class DatasetManifest:
    layer: str
    generated_at: str
    generator_model: str
    source_files: tuple[dict[str, Any], ...]
    record_count: int
    accepted_count: int
    gold_count: int
    policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def filter_candidates(
    records: Iterable[dict[str, Any]],
    *,
    evidence_ids: set[str] | None = None,
    generator_model: str = "unknown",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[CandidateDecision]]:
    """Return accepted candidates, rejected records, and auditable decisions.

    A candidate can be accepted for the filtered layer but never becomes gold
    automatically.  Gold promotion is a separate explicit operation.
    """

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    decisions: list[CandidateDecision] = []
    seen: set[str] = set()
    available = evidence_ids or set()
    for index, record in enumerate(records, start=1):
        record_id = str(record.get("id") or record.get("record_id") or f"candidate-{index:05d}")
        fingerprint = _fingerprint(record)
        group = str(record.get("source_group") or record.get("case_id") or re.sub(r"-v\d+$", "", record_id))
        split = _split_for_group(group)
        reasons: list[str] = []
        if fingerprint in seen:
            reasons.append("duplicate")
        seen.add(fingerprint)
        messages = record.get("messages")
        if not isinstance(messages, list) or not messages:
            reasons.append("messages_missing")
        raw_text = json.dumps(record, ensure_ascii=False)
        if inspect_sensitive_data(raw_text).blocked:
            reasons.append("pii_or_secret_detected")
        if inspect_untrusted_input(raw_text).blocked:
            reasons.append("instruction_like_content_detected")
        answer = _assistant_json(messages)
        if answer is None:
            reasons.append("assistant_json_invalid")
        else:
            try:
                if answer.get("schema_version") == "2.0":
                    parsed = SolutionResponseV2.model_validate(answer)
                    referenced = {
                        evidence_id for claim in parsed.claims for evidence_id in claim.evidence_ids
                    }
                else:
                    validate_solution_dict(answer, require_all_fields=False)
                    referenced = {
                        item.get("evidence_id")
                        for item in answer.get("evidence", [])
                        if isinstance(item, dict)
                    }
                if evidence_ids is not None and not referenced.issubset(available):
                    reasons.append("unknown_evidence_reference")
            except (TypeError, ValueError) as exc:
                reasons.append("schema_invalid:" + str(exc)[:160])
        decision = CandidateDecision(record_id, not reasons, tuple(reasons), fingerprint, group, split)
        decisions.append(decision)
        enriched = dict(record)
        enriched["pipeline"] = {
            "fingerprint": fingerprint,
            "source_group": group,
            "split": split,
            "generator_model": generator_model,
            "filtered_at": _utc_now(),
        }
        (accepted if not reasons else rejected).append(enriched)
    return accepted, rejected, decisions


def promote_expert_verified(
    filtered_records: Iterable[dict[str, Any]], approved_record_ids: set[str]
) -> list[dict[str, Any]]:
    """Promote only explicitly reviewed IDs, keeping the approval marker."""

    gold: list[dict[str, Any]] = []
    for record in filtered_records:
        record_id = str(record.get("id") or record.get("record_id"))
        if record_id not in approved_record_ids:
            continue
        enriched = dict(record)
        pipeline = dict(enriched.get("pipeline") or {})
        pipeline.update({"layer": "expert_verified_gold", "expert_verified": True, "verified_at": _utc_now()})
        enriched["pipeline"] = pipeline
        gold.append(enriched)
    return gold


def build_manifest(
    *,
    layer: str,
    source_files: Iterable[str],
    records: list[dict[str, Any]],
    accepted_count: int,
    gold_count: int = 0,
    generator_model: str = "unknown",
) -> DatasetManifest:
    files = []
    for path in source_files:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        files.append({"path": path, "sha256": digest})
    return DatasetManifest(
        layer=layer,
        generated_at=_utc_now(),
        generator_model=generator_model,
        source_files=tuple(files),
        record_count=len(records),
        accepted_count=accepted_count,
        gold_count=gold_count,
        policy={
            "same_source_group_stays_in_one_split": True,
            "model_generated_is_not_gold": True,
            "pii_scan": True,
            "citation_existence_check": True,
        },
    )


def _assistant_json(messages: Any) -> dict[str, Any] | None:
    if not isinstance(messages, list):
        return None
    for item in reversed(messages):
        if isinstance(item, dict) and item.get("role") == "assistant":
            content = str(item.get("content", "")).strip()
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if not match:
                    return None
                try:
                    payload = json.loads(match.group(0))
                except json.JSONDecodeError:
                    return None
            return payload if isinstance(payload, dict) else None
    return None


def _fingerprint(record: dict[str, Any]) -> str:
    canonical = json.dumps(record.get("messages", record), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _split_for_group(group: str) -> str:
    bucket = int(hashlib.sha256(group.encode("utf-8")).hexdigest()[:8], 16) % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "dev"
    return "test"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
