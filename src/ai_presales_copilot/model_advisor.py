"""Conservative model, retrieval, fine-tuning, and serving recommendations."""

from __future__ import annotations

import re
from typing import Any

from .schemas import CustomerBrief


def peak_concurrency(value: str) -> int | None:
    """Extract an explicitly stated peak concurrency without inventing one."""

    match = re.search(r"(?:峰值|并发)[^\d]{0,12}(\d+)", value or "")
    return int(match.group(1)) if match else None


def recommend_model_strategy(brief: CustomerBrief) -> dict[str, Any]:
    """Return a decision record that can be shown directly in a presales demo."""

    concurrency = peak_concurrency(brief.concurrency)
    private_data = brief.deployment in {"私有化", "内网", "本地"} or bool(
        set(brief.compliance) & {"数据不能出域", "敏感数据"}
    )

    if private_data and concurrency is not None and concurrency > 8:
        primary = "vLLM + LoRA（目标硬件复测）"
        serving_reason = "私有化且并发较高，优先验证批处理、KV Cache 和并发吞吐。"
    elif private_data:
        primary = "llama.cpp + GGUF 量化（目标硬件复测）"
        serving_reason = "数据不出域且并发较低，先用本地量化服务验证可行性和资源占用。"
    elif brief.deployment == "公有云 API":
        primary = "云端 API（POC 基线）"
        serving_reason = "客户已接受公有云 API，优先缩短 POC 周期并建立质量基线。"
    else:
        primary = "混合路线：云端 API 建基线 + 本地服务做边界验证"
        serving_reason = "部署边界尚未确认，先并行建立质量基线和私有化可行性证据。"

    return {
        "primary_serving_path": primary,
        "fallback_serving_path": "OpenAI-compatible API，便于在云端、vLLM 和 llama.cpp 之间切换",
        "retrieval_strategy": "RAG-first：产品事实、版本和持续更新内容不写进模型权重",
        "fine_tuning_strategy": "仅在 Prompt + RAG 基线稳定后，用 LoRA/QLoRA 优化格式、风格、分类和工具参数",
        "quantization_strategy": "在目标任务集上对 Q4/Q8 比较质量、TTFT、p95、吞吐和内存，不依据文件大小单独决策",
        "serving_reason": serving_reason,
        "decision_inputs": {
            "private_data_boundary": private_data,
            "peak_concurrency": concurrency,
            "latency_requirement": brief.latency_requirement,
            "deployment": brief.deployment,
        },
        "validation_before_commitment": [
            "在客户真实黄金问题集上比较 base 与 adapter",
            "在客户目标硬件、上下文长度和峰值并发下复测容量",
            "由安全/法务确认数据驻留、权限、日志和合规边界",
        ],
    }
