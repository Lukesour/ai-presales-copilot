"""Requirements-first intake, normalization, and completeness policy.

The model is allowed to propose extracted facts, but it is not allowed to
decide whether a presales run is ready for solution generation.  That decision
belongs to this deterministic module so the UI, API, replay snapshots, and
tests all share one gate.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .schemas import (
    ClarificationQuestionV2,
    CustomerBriefV2,
    InputTurnV2,
    IntakeBriefV2,
    RequirementAssessmentV2,
    RequirementConflictV2,
    RequirementFactV2,
    RequirementOverrideV2,
)


@dataclass(frozen=True)
class FieldDefinition:
    path: str
    display_name: str
    importance: str
    question: str
    why_it_matters: str
    answer_type: str = "text"


FIELD_CATALOG: tuple[FieldDefinition, ...] = (
    FieldDefinition(
        "business_goal",
        "业务目标",
        "blocking",
        "希望通过这个方案改善什么业务结果？例如减少检索时间、降低停机损失或提高一次解决率。",
        "没有业务目标就无法定义 PoC 价值和验收标准。",
    ),
    FieldDefinition(
        "use_case",
        "业务场景",
        "blocking",
        "请明确希望 AI 参与哪一个具体业务流程？",
        "场景决定知识范围、工作流和输出边界。",
    ),
    FieldDefinition(
        "target_users",
        "目标用户/业务流程",
        "blocking",
        "谁会使用这个能力？请说明角色、使用频率和要改造的现有流程。",
        "用户角色和流程决定权限、交互方式、集成边界和成功指标。",
        "list",
    ),
    FieldDefinition(
        "data_types",
        "数据来源",
        "blocking",
        "系统需要使用哪些资料或业务数据？资料位于哪些系统中？",
        "数据可得性和权限决定 RAG 是否可行。",
        "list",
    ),
    FieldDefinition(
        "deployment",
        "部署方式",
        "blocking",
        "请确认公有云、私有化、内网、边缘还是混合部署。",
        "部署边界会直接影响模型、网络和运维方案。",
        "choice",
    ),
    FieldDefinition(
        "governance.residency",
        "数据驻留/出域",
        "blocking",
        "数据是否允许出域？数据驻留区域和数据分类是什么？",
        "这是云端 API、本地模型和审计策略的前置约束。",
    ),
    FieldDefinition(
        "acceptance_criteria",
        "验收标准",
        "blocking",
        "POC 通过的判断标准是什么？请给出可测量的业务或技术指标。",
        "没有验收标准就无法判断 POC 是否成功。",
        "list",
    ),
    FieldDefinition(
        "industry",
        "行业",
        "warning",
        "客户所在行业或业务领域是什么？",
        "行业信息有助于选择知识库和风险边界。",
    ),
    FieldDefinition(
        "capacity.peak_concurrency",
        "峰值并发",
        "warning",
        "预计平均并发、峰值并发和日请求量分别是多少？",
        "没有容量输入时不能做生产规模和硬件承诺。",
        "number",
    ),
    FieldDefinition(
        "capacity.latency_target",
        "时延目标",
        "warning",
        "首 Token 和完整答案的时延目标分别是多少？",
        "时延目标会影响模型、量化、上下文和硬件选择。",
        "number",
    ),
    FieldDefinition(
        "integrations",
        "集成系统",
        "warning",
        "需要接入哪些文档库、业务系统、身份系统或审计平台？",
        "集成边界会影响工作量和部署架构。",
        "list",
    ),
    FieldDefinition(
        "budget",
        "预算",
        "warning",
        "是否有 PoC 或生产预算范围？",
        "预算决定云端、本地硬件和交付范围。",
    ),
    FieldDefinition(
        "timeline",
        "时间计划",
        "warning",
        "希望何时完成 PoC、试点和生产上线？",
        "时间约束会影响 POC 范围和交付路线。",
    ),
    FieldDefinition(
        "governance.audit_required",
        "审计要求",
        "warning",
        "是否要求保留访问、引用、审核和模型运行审计？",
        "审计要求决定日志、权限和人工审核设计。",
        "boolean",
    ),
)

FIELD_BY_PATH = {item.path: item for item in FIELD_CATALOG}
BLOCKING_FIELDS = tuple(item.path for item in FIELD_CATALOG if item.importance == "blocking")
WARNING_FIELDS = tuple(item.path for item in FIELD_CATALOG if item.importance == "warning")


def field_definition(path: str) -> FieldDefinition:
    if path == "governance.egress_allowed":
        return FieldDefinition(
            path,
            "数据出域",
            "warning",
            "数据是否允许离开当前部署边界？",
            "出域约束会影响模型服务、网络和合规方案。",
            "boolean",
        )
    return FIELD_BY_PATH.get(
        path,
        FieldDefinition(path, path, "warning", f"请补充 {path}。", "该信息会影响方案边界。"),
    )



def validate_fact_sources(
    facts: Iterable[RequirementFactV2], turns: Iterable[InputTurnV2]
) -> None:
    """Reject model attributions that cannot be found in customer text."""

    turns_by_id = {turn.turn_id: turn.content for turn in turns}
    for fact in facts:
        if fact.status not in {"stated", "confirmed"}:
            continue
        if not fact.source_turn_id or fact.source_turn_id not in turns_by_id:
            raise ValueError(f"fact {fact.field_path} references an unknown source turn")
        if not fact.source_quote or fact.source_quote not in turns_by_id[fact.source_turn_id]:
            raise ValueError(f"fact {fact.field_path} source_quote is not present in source turn")
        if fact.start_char is not None and fact.end_char is not None:
            source = turns_by_id[fact.source_turn_id]
            if source[fact.start_char : fact.end_char] != fact.source_quote:
                raise ValueError(f"fact {fact.field_path} source span does not match source_quote")


def fact_map(facts: Iterable[RequirementFactV2]) -> dict[str, RequirementFactV2]:
    """Prefer confirmed facts, then stated facts, over inferred candidates."""

    priority = {"confirmed": 4, "stated": 3, "ambiguous": 2, "conflicting": 2, "inferred": 1, "missing": 0}
    result: dict[str, RequirementFactV2] = {}
    for fact in facts:
        previous = result.get(fact.field_path)
        if previous is None or priority.get(fact.status, 0) >= priority.get(previous.status, 0):
            result[fact.field_path] = fact
    return result


def detect_fact_conflicts(
    facts: Iterable[RequirementFactV2],
) -> list[RequirementConflictV2]:
    """Detect contradictory customer statements before the solution gate.

    The model may explicitly return conflicts, but duplicate field facts are
    cheap to check deterministically and should not depend on a second model
    judgment.  A confirmed value is still surfaced alongside an older stated
    value so the customer can see and resolve the change explicitly.
    """

    grouped: dict[str, list[RequirementFactV2]] = {}
    for fact in facts:
        if fact.status not in {"stated", "confirmed"} or not fact.value_text:
            continue
        grouped.setdefault(fact.field_path, []).append(fact)
    conflicts: list[RequirementConflictV2] = []
    for path, candidates in grouped.items():
        distinct: dict[str, RequirementFactV2] = {}
        for fact in candidates:
            normalized = _normalize_fact_value(path, fact.value_text)
            distinct.setdefault(normalized, fact)
        if len(distinct) < 2:
            continue
        values = "；".join(item.value_text or "" for item in distinct.values())
        source_turn_ids = list(
            dict.fromkeys(
                fact.source_turn_id
                for fact in candidates
                if fact.source_turn_id
            )
        )
        definition = field_definition(path)
        conflicts.append(
            RequirementConflictV2(
                field_path=path,
                description=f"客户对「{definition.display_name}」给出了互相矛盾的值：{values}。",
                source_turn_ids=source_turn_ids,
                resolution_question=f"请确认「{definition.display_name}」的最终要求。",
            )
        )
    return conflicts


def _normalize_fact_value(field_path: str, value: str) -> str:
    """Normalize equivalent model phrasings before declaring a conflict."""

    normalized = re.sub(r"\s+", "", value.strip()).casefold()
    if field_path != "deployment":
        return normalized
    # Deployment is layered: "public-cloud deployment + public-cloud API" is
    # one architecture, not two mutually exclusive deployment choices.
    if "公有云" in normalized and "api" in normalized:
        return "public_cloud_api"
    if "公有云" in normalized:
        return "public_cloud"
    if "企业内网" in normalized or "内网" in normalized or "私有化" in normalized:
        return "private_network"
    if "边缘" in normalized:
        return "edge"
    if "本地" in normalized:
        return "on_premises"
    if "混合" in normalized:
        return "hybrid"
    return normalized


def _deduplicate_conflicts(
    conflicts: Iterable[RequirementConflictV2],
) -> list[RequirementConflictV2]:
    """Keep one actionable clarification per field while merging provenance."""

    merged: dict[tuple[str, str], RequirementConflictV2] = {}
    for conflict in conflicts:
        key = (conflict.field_path, conflict.resolution_question)
        previous = merged.get(key)
        if previous is None:
            merged[key] = conflict
            continue
        source_turn_ids = list(
            dict.fromkeys([*previous.source_turn_ids, *conflict.source_turn_ids])
        )
        description = previous.description
        if conflict.description not in description:
            description = f"{description}；{conflict.description}"
        merged[key] = previous.model_copy(
            update={"description": description, "source_turn_ids": source_turn_ids}
        )
    return list(merged.values())


def _brief_value(brief: IntakeBriefV2, path: str) -> Any:
    if path == "capacity.latency_target":
        return brief.capacity.full_answer_target_ms or brief.capacity.ttft_target_ms
    if path.startswith("capacity."):
        return getattr(brief.capacity, path.split(".", 1)[1], None)
    if path.startswith("governance."):
        return getattr(brief.governance, path.split(".", 1)[1], None)
    return getattr(brief, path, None)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip() != "未说明"
    if isinstance(value, (list, tuple, set)):
        return bool(value)
    return True


def _is_blocked(path: str, brief: IntakeBriefV2, facts: dict[str, RequirementFactV2]) -> bool:
    fact = facts.get(path)
    if path == "governance.residency" and brief.governance.egress_allowed is not None:
        return bool(fact and fact.status in {"ambiguous", "conflicting"})
    if fact and fact.status in {"missing", "ambiguous", "conflicting", "inferred"}:
        return True
    if path == "governance.residency":
        # A customer can satisfy the data-boundary requirement either by
        # naming a residency boundary or by explicitly stating whether data
        # may leave that boundary.  Do not force a second answer for the same
        # control when one explicit boundary decision is already present.
        return not (
            _has_value(brief.governance.residency)
            or brief.governance.egress_allowed is not None
        )
    return not _has_value(_brief_value(brief, path))


def assess_requirements(
    brief: IntakeBriefV2,
    facts: Iterable[RequirementFactV2],
    conflicts: Iterable[RequirementConflictV2],
    *,
    clarification_turns: int = 0,
) -> RequirementAssessmentV2:
    """Compute readiness without delegating the gate to the LLM."""

    fact_items = list(facts)
    indexed = fact_map(fact_items)
    conflict_items = _deduplicate_conflicts(conflicts)
    known_conflict_paths = {item.field_path for item in conflict_items}
    conflict_items.extend(
        item
        for item in detect_fact_conflicts(fact_items)
        if item.field_path not in known_conflict_paths
    )
    blocking = [
        path for path in BLOCKING_FIELDS if _is_blocked(path, brief, indexed)
    ]
    blocking.extend(item.field_path for item in conflict_items if item.field_path not in blocking)

    warnings = [
        path
        for path in WARNING_FIELDS
        if not _has_value(_brief_value(brief, path))
        and path not in blocking
    ]
    questions: list[ClarificationQuestionV2] = []
    for path in [*blocking, *warnings]:
        definition = field_definition(path)
        conflict = next((item for item in conflict_items if item.field_path == path), None)
        questions.append(
            ClarificationQuestionV2(
                question_id=f"question-{path.replace('.', '-')}",
                field_path=path,
                question=conflict.resolution_question if conflict else definition.question,
                why_it_matters=conflict.description if conflict else definition.why_it_matters,
                importance="blocking" if path in blocking else "warning",
                answer_type=definition.answer_type,
            )
        )
    return RequirementAssessmentV2(
        ready_for_confirmation=not blocking,
        blocking_fields=list(dict.fromkeys(blocking)),
        warning_fields=list(dict.fromkeys(warnings)),
        conflicts=conflict_items,
        questions=questions[:4],
        clarification_turns=clarification_turns,
    )


def apply_override(brief: IntakeBriefV2, override: RequirementOverrideV2) -> IntakeBriefV2:
    """Apply a user-edited field value using explicit, bounded paths."""

    value = override.value_text.strip()
    path = override.field_path
    data = brief.model_dump(mode="python")
    if path in {"target_users", "data_types", "integrations", "acceptance_criteria"}:
        data[path] = [item.strip() for item in re.split(r"[,，、;；\n]", value) if item.strip()]
    elif path == "governance.egress_allowed":
        normalized = value.lower().strip()
        positive = normalized in {"true", "yes", "是", "允许", "可以", "允许出域", "可出域"}
        positive = positive or (
            normalized.startswith("是")
            and not normalized.startswith("不是")
        )
        positive = positive or (
            any(token in normalized for token in ("允许", "可以", "可出域"))
            and not any(token in normalized for token in ("不允许", "不能", "不可", "禁止"))
        )
        if positive:
            data["governance"]["egress_allowed"] = True
        elif normalized in {"false", "no", "否", "不允许", "不能", "不可出域", "数据不能出域"} or any(
            token in normalized for token in ("不允许", "不能", "不可", "禁止")
        ):
            data["governance"]["egress_allowed"] = False
        else:
            raise ValueError("governance.egress_allowed must be boolean-like")
    elif path == "governance.audit_required":
        normalized = value.lower().strip()
        positive = normalized in {"true", "yes", "是", "需要", "要求", "必须"}
        positive = positive or (normalized.startswith("是") and not normalized.startswith("不是")) or (
            any(token in normalized for token in ("需要", "要求", "必须"))
            and not any(token in normalized for token in ("不需要", "无需", "不要求"))
        )
        if positive:
            data["governance"]["audit_required"] = True
        elif normalized in {"false", "no", "否", "不需要", "无需", "不要求"}:
            data["governance"]["audit_required"] = False
        else:
            raise ValueError("governance.audit_required must be boolean-like")
    elif path.startswith("governance."):
        data["governance"][path.split(".", 1)[1]] = value
    elif path.startswith("capacity."):
        target = path.split(".", 1)[1]
        if target == "latency_target":
            target = "full_answer_target_ms"
        numeric = re.search(r"\d+(?:\.\d+)?", value)
        if numeric is None:
            raise ValueError(f"{path} must be numeric")
        number = float(numeric.group(0))
        if target == "full_answer_target_ms" and "秒" in value and "毫秒" not in value:
            number *= 1000
        data["capacity"][target] = int(number)
    elif path in FIELD_BY_PATH:
        data[path] = value
    else:
        raise ValueError(f"unsupported requirement field: {path}")
    return IntakeBriefV2.model_validate(data)


def to_solution_brief(brief: IntakeBriefV2) -> CustomerBriefV2:
    """Convert a confirmed intake brief into the existing solution contract."""

    return CustomerBriefV2(
        schema_version="2.0",
        case_id=brief.case_id,
        industry=brief.industry or "企业",
        business_goal=brief.business_goal,
        use_case=brief.use_case or "待确认的 AI 解决方案",
        target_users=list(brief.target_users),
        current_process=brief.current_process,
        data_types=list(brief.data_types),
        deployment=brief.deployment or "未说明",
        capacity=brief.capacity,
        governance=brief.governance,
        budget=brief.budget or "未说明",
        timeline=brief.timeline,
        integrations=list(brief.integrations),
        acceptance_criteria=list(brief.acceptance_criteria),
        raw_request=brief.raw_request,
    )


def merge_fact_lists(
    existing: Iterable[RequirementFactV2], incoming: Iterable[RequirementFactV2]
) -> list[RequirementFactV2]:
    """Merge facts while retaining contradictory values for the conflict gate.

    A model extraction is allowed to omit a field on a later turn.  Its
    materialized ``missing`` row must therefore never overwrite an earlier
    ``stated``/``confirmed`` fact.  Explicit confirmations still win in the
    selected ``fact_map``, while a different stated value remains in the list
    so the deterministic conflict gate can require an explicit resolution.
    """

    priority = {
        "confirmed": 5,
        "stated": 4,
        "conflicting": 3,
        "ambiguous": 2,
        "inferred": 1,
        "missing": 0,
    }
    merged = list(existing)
    for item in incoming:
        same_field = [
            (index, previous)
            for index, previous in enumerate(merged)
            if previous.field_path == item.field_path
        ]
        substantive = item.status in {"stated", "confirmed"}
        if substantive:
            merged = [
                previous
                for previous in merged
                if not (
                    previous.field_path == item.field_path
                    and previous.status in {"missing", "inferred", "ambiguous"}
                )
            ]
            same_field = [
                (index, previous)
                for index, previous in enumerate(merged)
                if previous.field_path == item.field_path
            ]
        if not same_field:
            merged.append(item)
            continue
        equivalent = [
            (index, previous)
            for index, previous in same_field
            if not previous.value_text
            or not item.value_text
            or _normalize_fact_value(item.field_path, previous.value_text)
            == _normalize_fact_value(item.field_path, item.value_text)
        ]
        if equivalent:
            index, previous = equivalent[-1]
            if priority[item.status] >= priority[previous.status]:
                merged[index] = item
            continue
        # Keep a different stated/confirmed value as historical evidence; it
        # is intentionally surfaced by detect_fact_conflicts.
        if priority[item.status] >= max(priority[previous.status] for _, previous in same_field):
            merged.append(item)
    return merged
