# 评测方案与当前证据

## 评测分层

| 层级 | 问题 | 当前入口 |
|---|---|---|
| 契约 | JSON 是否可解析、必需字段是否完整 | `pytest`、`validate_solution_dict(require_all_fields=True)` |
| Agent | 节点是否完成、POC/模型策略是否存在、审核门是否触发 | `make agent-eval` |
| 检索 | 是否有来源；无召回是否保守 | `data/evaluation/cases.jsonl` |
| 安全 | 注入、无依据承诺、敏感数据 | `make security-check` / `scripts/run_security_checks.py` |
| 微调 | 数据格式、RAG context、target schema、case-level split、hash、token overflow | `make dataset-check` / `make finetune-token-audit` |
| 推理 | TTFT、p95、吞吐、RSS/VRAM、结构化 JSON | Colab notebook + `benchmark_llama.py` |

## 运行命令

```bash
make test
make lint
make eval
make agent-eval
PYTHONPATH=src python scripts/run_security_checks.py
make build-finetune-dataset
make dataset-check
make finetune-dry-run
```

## 当前离线证据

在本机依赖环境中，最近一次可复现结果为：

- Python 单元测试：41 passed。
- Agent 24 条案例：24/24 完成；schema、POC、model strategy、证据/保守无证据规则和审核门均通过。
- 红队策略用例：12/12 通过。
- 微调数据：72 条对话，按 24 个源案例做 case-level split；train 42、dev 12、test 18，每个源案例最多 3 个变体；输入包含结构化客户约束和检索上下文，target 为紧凑 JSON。

这些数字证明的是离线契约和规则，不是模型业务准确率，也不是客户生产容量。真正的 LLM 质量报告必须另存 base/adapter、模型 revision、评测提示词、人工评分规则和完整原始输出。

## Colab QLoRA 实测证据

commit `095109616c99fe665d296eaab0eebe1b6bd5818b` 在 Tesla T4 上完成了 `compact` model-facing contract 实验。完整的小型摘要报告保存在 [`compact-experiment-20260909.json`](../data/results/colab/qlora/compact-experiment-20260909.json)；adapter 权重和完整运行 bundle 仅保存在 Google Drive，不提交到 GitHub。

| 指标 | Base | Adapter | 口径 |
| --- | ---: | ---: | --- |
| JSON parse rate | 100% | 100% | 18 条 held-out synthetic test cases |
| compact schema pass rate | 0% | 77.78%（14/18） | 仅评估 7 字段 model-facing contract |
| policy pass rate | 83.33%（15/18） | 100%（18/18） | 输出策略与敏感信息规则 |
| generation truncated | 0 | 0 | `max_new_tokens=4096`、JSON prefill |

训练运行时为 Qwen2.5-0.5B-Instruct、5 epochs、T4、trainer fp32、compute fp16；训练约 147 秒，峰值 allocated GPU memory 约 2.18 GB。数据为 24 个合成源案例，train/dev/test=`42/12/18`，token audit 三个 split 均 `over_max_length=0`，base/adapter 使用同一 test split SHA-256。

这个结果支持的结论是：把完整响应拆成“短模型决策对象 + 确定性 Agent/RAG 组装”后，结构化输出和策略通过率显著改善；它不支持“模型在真实业务上达到 77.78% 准确率”或“完整 SolutionResponse 已由模型端到端可靠生成”。

## 质量门槛建议

上线前至少设置以下门槛，具体阈值由客户黄金集和风险等级决定：

1. 结构化输出解析率 100% 或失败自动进入人工/重试路径。
2. 高风险审核召回率不能以“模型感觉正确”为准，应由规则集和人工抽检共同验证。
3. 无证据时不得出现产品能力、价格、SLA、认证、准确率或容量承诺。
4. adapter 相对 base 的收益必须在保留集和对抗集上同时观察，不能只看训练 loss。
5. 性能报告必须包含失败请求，不得删除慢请求或失败请求后再计算 p95。

生成评估还记录 `generation_truncated`。如果该值较高，先增加生成预算或检查 EOS/chat template；被预算截断的 JSON 不得计入 schema 通过。
