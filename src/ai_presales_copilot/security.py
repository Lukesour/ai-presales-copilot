"""Input and output policy checks used by the Agent risk gate."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

INJECTION_PATTERNS = (
    re.compile(r"忽略(?:之前|以上|所有)(?:指令|规则)", re.IGNORECASE),
    re.compile(r"ignore\s+(?:(?:all\s+)?(?:previous|prior|above|earlier))\s+instructions", re.IGNORECASE),
    re.compile(r"泄露(?:系统提示词|提示词|system prompt)", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"输出你的(?:密钥|秘密|内部规则)", re.IGNORECASE),
)

EXCESSIVE_AGENCY_PATTERNS = (
    re.compile(r"(?:删除|修改|清理).{0,20}(?:工具|生产|数据库|权限)", re.IGNORECASE),
    re.compile(r"(?:delete|modify|change|drop).{0,24}(?:production|database|permission|tool)", re.IGNORECASE),
)

UNBOUNDED_CONSUMPTION_PATTERNS = (
    re.compile(r"无限(?:循环|调用|重试)", re.IGNORECASE),
    re.compile(r"(?:loop|retry|call).{0,16}(?:forever|indefinitely|without limit)", re.IGNORECASE),
)

UNSUPPORTED_COMMITMENT_PATTERNS = (
    re.compile(r"(?:保证|承诺|确保).{0,12}(?:99\.9|100%|SLA|准确率)", re.IGNORECASE),
    re.compile(r"(?:certified|guarantee|guaranteed).{0,20}(?:accuracy|SLA|compliance)", re.IGNORECASE),
    re.compile(r"(?:已认证|通过认证|符合全部监管要求)", re.IGNORECASE),
)

SENSITIVE_DATA_PATTERNS = (
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"\b\d{17}[\dXx]\b"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?:公开|外发|泄露|写入).{0,20}(?:邮箱|手机号|身份证)", re.IGNORECASE),
    re.compile(r"(?:邮箱|手机号|身份证).{0,20}(?:公开|外发|泄露|trace)", re.IGNORECASE),
)


@dataclass(frozen=True)
class PolicyResult:
    blocked: bool
    categories: list[str] = field(default_factory=list)
    matches: list[str] = field(default_factory=list)


def inspect_untrusted_input(text: str) -> PolicyResult:
    source = text or ""
    matches: list[str] = []
    categories: list[str] = []
    if any(pattern.search(source) for pattern in INJECTION_PATTERNS):
        categories.append("prompt_injection")
        matches.extend(pattern.pattern for pattern in INJECTION_PATTERNS if pattern.search(source))
    if any(pattern.search(source) for pattern in EXCESSIVE_AGENCY_PATTERNS):
        categories.append("excessive_agency")
        matches.extend(
            pattern.pattern for pattern in EXCESSIVE_AGENCY_PATTERNS if pattern.search(source)
        )
    if any(pattern.search(source) for pattern in UNBOUNDED_CONSUMPTION_PATTERNS):
        categories.append("unbounded_consumption")
        matches.extend(
            pattern.pattern
            for pattern in UNBOUNDED_CONSUMPTION_PATTERNS
            if pattern.search(source)
        )
    return PolicyResult(bool(matches), categories, matches)


def inspect_output(text: str) -> PolicyResult:
    matches = [pattern.pattern for pattern in UNSUPPORTED_COMMITMENT_PATTERNS if pattern.search(text or "")]
    return PolicyResult(bool(matches), ["unsupported_commitment"] if matches else [], matches)


def inspect_sensitive_data(text: str) -> PolicyResult:
    matches = [pattern.pattern for pattern in SENSITIVE_DATA_PATTERNS if pattern.search(text or "")]
    return PolicyResult(bool(matches), ["sensitive_data"] if matches else [], matches)


def wrap_untrusted_text(text: str) -> str:
    """Make the trust boundary explicit when the text is passed to an LLM."""

    return f"<untrusted_customer_data>\n{text}\n</untrusted_customer_data>"
