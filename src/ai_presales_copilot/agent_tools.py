"""Explicit, bounded tools exposed to the presales Agent."""

from __future__ import annotations

from typing import Any

from .knowledge import KnowledgeBase
from .model_advisor import peak_concurrency
from .schemas import CustomerBrief, Evidence

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_knowledge",
        "description": "Search versioned solution and deployment material.",
        "input_schema": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
    },
    {
        "name": "validate_evidence",
        "description": "Check that factual claims have evidence IDs.",
        "input_schema": {"type": "object", "required": ["evidence_ids"], "properties": {"evidence_ids": {"type": "array"}}},
    },
    {
        "name": "estimate_capacity",
        "description": "Classify capacity validation needs without inventing throughput numbers.",
        "input_schema": {"type": "object", "required": ["concurrency"], "properties": {"concurrency": {"type": "string"}}},
    },
    {
        "name": "compare_deployment_options",
        "description": "Compare cloud, local, and production serving boundaries.",
        "input_schema": {"type": "object", "required": ["deployment"], "properties": {"deployment": {"type": "string"}}},
    },
]


class PresalesTools:
    """Tools with narrow inputs and deterministic output for tests and demos."""

    def __init__(self, knowledge_base: KnowledgeBase):
        self.knowledge_base = knowledge_base

    def search_knowledge(self, query: str, top_k: int = 5) -> list[Evidence]:
        return self.knowledge_base.search(query, top_k=top_k)

    @staticmethod
    def validate_evidence(evidence: list[Evidence]) -> dict[str, Any]:
        ids = [item.evidence_id for item in evidence if item.evidence_id.strip()]
        return {
            "valid": bool(ids),
            "evidence_ids": ids,
            "reason": "至少有一个带来源的证据片段" if ids else "没有可支持事实结论的证据",
        }

    @staticmethod
    def estimate_capacity(brief: CustomerBrief) -> dict[str, Any]:
        concurrency = peak_concurrency(brief.concurrency)
        if concurrency is None:
            return {
                "status": "needs_confirmation",
                "peak_concurrency": None,
                "required_inputs": ["平均并发", "峰值并发", "日请求量", "上下文长度", "完整答案目标"],
                "recommendation": "补充容量输入后，在目标硬件上压测。",
            }
        return {
            "status": "requires_benchmark",
            "peak_concurrency": concurrency,
            "candidate_path": "vLLM/云端服务" if concurrency > 8 else "llama.cpp 或轻量本地服务",
            "recommendation": "该分类只用于选择压测路径，不代表任何可承诺的吞吐或 SLA。",
        }

    @staticmethod
    def compare_deployment_options(brief: CustomerBrief) -> list[dict[str, Any]]:
        private = brief.deployment in {"私有化", "内网", "本地"} or "数据不能出域" in brief.compliance
        return [
            {
                "option": "云端 API",
                "fit": "需确认数据出域" if private else "POC 优先",
                "advantages": ["上线快", "模型质量基线容易建立", "免维护推理硬件"],
                "validate": ["数据驻留", "供应商可用性", "Token 成本", "限流"],
            },
            {
                "option": "本地 llama.cpp",
                "fit": "适合低并发私有化验证" if private else "边缘/低流量备选",
                "advantages": ["数据留在本地", "模型版本固定", "OpenAI-compatible 接口"],
                "validate": ["目标硬件质量与容量", "量化损失", "升级和运维"],
            },
            {
                "option": "vLLM 生产服务",
                "fit": "适合共享 GPU 和较高并发",
                "advantages": ["批处理和并发能力", "LoRA 适配器服务", "集中运维"],
                "validate": ["GPU 采购", "隔离", "显存", "多 LoRA 管理", "高可用"],
            },
        ]
