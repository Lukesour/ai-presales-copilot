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
    RequirementExtractionV2,
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


def conservative_extract_requirements(
    raw_request: str,
    *,
    case_id: str,
    turn_id: str = "turn-1",
) -> RequirementExtractionV2:
    """Extract only high-confidence lexical facts when the model is unusable.

    This is a safety fallback for local model/schema incompatibilities.  It
    never invents values: every emitted fact carries an exact substring from
    the raw request, and anything not recognized remains null/empty so the
    deterministic assessment can ask the customer.
    """

    text = raw_request.strip()
    brief_data: dict[str, Any] = {
        "schema_version": "2.0",
        "case_id": case_id,
        "raw_request": raw_request,
    }
    facts: list[RequirementFactV2] = []

    def add_fact(
        path: str,
        value: Any,
        quote: str | None,
        *,
        status: str = "stated",
    ) -> None:
        if value in (None, "", [], {}):
            return
        source_quote = (quote or "").strip()
        if not source_quote or source_quote not in text:
            return
        definition = field_definition(path)
        if isinstance(value, list):
            value_text = "、".join(str(item) for item in value)
        elif isinstance(value, bool):
            value_text = "true" if value else "false"
        else:
            value_text = str(value)
        facts.append(
            RequirementFactV2(
                field_path=path,
                display_name=definition.display_name,
                value_text=value_text,
                status=status,
                importance=definition.importance,
                confidence=0.9 if status == "stated" else None,
                source_turn_id=turn_id,
                source_quote=source_quote,
            )
        )

    def first_match(pattern: str, *, flags: int = 0) -> str | None:
        match = re.search(pattern, text, flags)
        return match.group(0).strip() if match else None

    industry = first_match(r"制造业|工业制造|制造行业")
    if industry:
        brief_data["industry"] = industry
        add_fact("industry", industry, industry)

    goal = first_match(r"(?:减少|降低|提升|提高|改善)[^。；，,\n]{1,40}")
    if goal:
        brief_data["business_goal"] = goal
        add_fact("business_goal", goal, goal)

    use_case = first_match(r"[^。；，,\n]{0,80}(?:知识助手|知识问答|智能问答|知识库)")
    if use_case:
        use_case = use_case.lstrip("客户希望想要把将")
        brief_data["use_case"] = use_case
        add_fact("use_case", use_case, use_case)

    user_matches = list(
        dict.fromkeys(
            re.findall(
                r"维修工程师|现场工程师|一线员工|操作员|客服|销售|医生|护士|管理人员",
                text,
            )
        )
    )
    if user_matches:
        brief_data["target_users"] = user_matches
        add_fact("target_users", user_matches, user_matches[0])

    data_match = re.search(
        r"((?:维修手册|历史工单|工单系统|产品文档|业务数据|知识库)"
        r"\s*(?:和|及|与|、|，|,)\s*(?:维修手册|历史工单|工单系统|产品文档|业务数据|知识库))",
        text,
    )
    data_values: list[str] = []
    data_quote: str | None = None
    if data_match:
        data_quote = data_match.group(1).strip()
        data_values = list(
            dict.fromkeys(
                item
                for item in re.split(r"\s*(?:和|及|与|、|，|,)\s*", data_quote)
                if item
            )
        )
    else:
        for keyword in ("维修手册", "历史工单", "工单系统", "产品文档", "业务数据"):
            if keyword in text:
                data_values.append(keyword)
        if data_values:
            data_quote = data_values[0]
    if data_values:
        brief_data["data_types"] = data_values
        add_fact("data_types", data_values, data_quote)

    deployment_matches = re.findall(
        r"企业内网(?:私有化)?|内网私有化|公有云\s*API|公有云|私有化|本地部署|边缘部署|混合部署",
        text,
    )
    deployment_values = list(dict.fromkeys(item.strip() for item in deployment_matches))
    deployment_conflict = len(deployment_values) > 1
    if deployment_values and not deployment_conflict:
        brief_data["deployment"] = deployment_values[0]
        add_fact("deployment", deployment_values[0], deployment_values[0])

    residency_match = re.search(r"中国境内|境内驻留", text)
    residency = residency_match.group(0) if residency_match else None
    egress_matches = list(
        dict.fromkeys(
            match.strip()
            for match in re.findall(r"(?:允许|可以|可)\s*(?:出域|外发)|(?:不能|不可|不允许|禁止|不得)\s*(?:出域|外发)", text)
        )
    )
    egress_values = [
        not bool(re.search(r"不能|不可|不允许|禁止|不得", item)) for item in egress_matches
    ]
    egress_conflict = len(set(egress_values)) > 1
    governance: dict[str, Any] = {}
    if residency and not residency.startswith("数据驻留"):
        governance["residency"] = residency
        add_fact("governance.residency", residency, residency)
    if egress_matches and not egress_conflict:
        governance["egress_allowed"] = egress_values[0]
        add_fact("governance.egress_allowed", egress_values[0], egress_matches[0])
    if "审计" in text:
        audit_quote = first_match(r"[^。；，,\n]{0,20}审计[^。；，,\n]{0,20}") or "审计"
        governance["audit_required"] = True
        add_fact("governance.audit_required", True, audit_quote)
    if governance:
        brief_data["governance"] = governance

    peak = re.search(r"峰值\s*并发\s*(?:为|是|:|：)?\s*(\d+)", text)
    if peak:
        brief_data.setdefault("capacity", {})["peak_concurrency"] = int(peak.group(1))
        add_fact("capacity.peak_concurrency", int(peak.group(1)), peak.group(0))
    latency = re.search(r"(?:完整答案|全答案|响应)\s*(?:不超过|不高于|目标)?\s*(\d+(?:\.\d+)?)\s*(秒|毫秒)", text)
    if latency:
        milliseconds = int(float(latency.group(1)) * (1000 if latency.group(2) == "秒" else 1))
        brief_data.setdefault("capacity", {})["full_answer_target_ms"] = milliseconds
        add_fact("capacity.latency_target", milliseconds, latency.group(0))

    acceptance = re.search(r"验收(?:要求|标准)?\s*(?:为|是|:|：)?\s*([^。；\n]+)", text)
    if acceptance:
        criterion = acceptance.group(1).strip()
        brief_data["acceptance_criteria"] = [criterion]
        add_fact("acceptance_criteria", [criterion], acceptance.group(0))

    integrations = [
        item
        for item in ("企业文档库", "统一身份认证", "审计平台", "内网文档库", "工单系统")
        if item in text
    ]
    if integrations:
        brief_data["integrations"] = list(dict.fromkeys(integrations))
        add_fact("integrations", brief_data["integrations"], integrations[0])

    conflict_items: list[RequirementConflictV2] = []
    if deployment_conflict:
        conflict_items.append(
            RequirementConflictV2(
                field_path="deployment",
                description=f"客户同时提到多个部署边界：{'、'.join(deployment_values)}。",
                source_turn_ids=[turn_id],
                resolution_question="请确认最终部署方式。",
            )
        )
    if egress_conflict:
        conflict_items.append(
            RequirementConflictV2(
                field_path="governance.residency",
                description="客户同时提出允许和禁止出域的要求。",
                source_turn_ids=[turn_id],
                resolution_question="请确认数据是否允许出域。",
            )
        )
    if deployment_conflict:
        brief_data["deployment"] = None
    if egress_conflict:
        governance["egress_allowed"] = None
        brief_data["governance"] = governance

    brief = IntakeBriefV2.model_validate(brief_data)
    return RequirementExtractionV2(
        schema_version="2.0",
        brief=brief,
        facts=facts,
        conflicts=conflict_items,
        assumptions=[],
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
            normalized = re.sub(r"\s+", " ", fact.value_text.strip()).casefold()
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
    conflict_items = list(conflicts)
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
        data[path] = [item.strip() for item in re.split(r"[,，;；\n]", value) if item.strip()]
    elif path == "governance.egress_allowed":
        if value.lower() in {"true", "yes", "允许", "可以", "可出域"}:
            data["governance"]["egress_allowed"] = True
        elif value.lower() in {"false", "no", "不允许", "不能", "不可出域", "数据不能出域"}:
            data["governance"]["egress_allowed"] = False
        else:
            raise ValueError("governance.egress_allowed must be boolean-like")
    elif path == "governance.audit_required":
        if value.lower() in {"true", "yes", "需要", "要求", "必须"}:
            data["governance"]["audit_required"] = True
        elif value.lower() in {"false", "no", "不需要", "无需", "不要求"}:
            data["governance"]["audit_required"] = False
        else:
            raise ValueError("governance.audit_required must be boolean-like")
    elif path.startswith("governance."):
        data["governance"][path.split(".", 1)[1]] = value
    elif path.startswith("capacity."):
        target = path.split(".", 1)[1]
        try:
            data["capacity"][target] = int(float(value))
        except ValueError as exc:
            raise ValueError(f"{path} must be numeric") from exc
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
    """Keep one auditable fact per field without erasing prior evidence.

    A model extraction is allowed to omit a field on a later turn.  Its
    materialized ``missing`` row must therefore never overwrite an earlier
    ``stated``/``confirmed`` fact.  Explicit confirmations still win over
    older customer statements.
    """

    merged: dict[str, RequirementFactV2] = {item.field_path: item for item in existing}
    priority = {
        "confirmed": 5,
        "stated": 4,
        "conflicting": 3,
        "ambiguous": 2,
        "inferred": 1,
        "missing": 0,
    }
    for item in incoming:
        previous = merged.get(item.field_path)
        if previous is None or priority[item.status] >= priority[previous.status]:
            merged[item.field_path] = item
    return list(merged.values())
