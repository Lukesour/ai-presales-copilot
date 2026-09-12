# 模型与部署实验

## 责任域

`llama_client.py`, `model_schemas.py`, `configs/finetune/`, `scripts/`, `notebooks/` and
`deploy/` 负责本地服务、部署比较、微调和基准证据。

## 决策边界

变化中的产品事实由 RAG 负责。只有在有可复现基线后，微调才可以编码稳定格式、分类、工具参数或工作流
行为。Cloud API、llama.cpp 和 vLLM 的结论必须注明目标硬件、模型 revision、上下文、采样参数和日期。

## 失败边界

本地模型缺失或输出非法时状态为 `model_unavailable`，不得转成确定性模板响应。训练和基准脚本必须保留
manifest、失败案例、截断信息和资源测量。

## 证据

- `docs/deployment-decision.md`
- `docs/fine-tuning.md`
- `docs/tco-and-sizing.md`
- `docs/colab-qlora-runbook.md`
- `data/results/README.md`
