# 评测方案与当前证据

## 评测分层

| 层级 | 问题 | 当前入口 |
|---|---|---|
| 需求抽取 | 字段值、状态、置信度和原文引用是否可验证 | `tests/test_requirements_first.py`、`RequirementExtractionV2` |
| 需求完整性 | 阻断/警告/冲突是否由确定性目录判断 | `src/ai_presales_copilot/requirements.py` |
| 契约 | JSON 是否可解析、必需字段是否完整 | `pytest`、`SolutionResponseV2` |
| 检索 | 是否召回允许使用的来源；未确认需求是否完全不检索 | `data/evaluation/replay_cases.jsonl`、`data/evaluation/manifest.json`、事件顺序断言 |
| Groundedness | 事实 Claim 是否绑定 evidence ID 和定位 | Claim—Evidence 校验 |
| 完整性 | 需求覆盖、POC 验收、风险和假设是否齐全 | `scripts/run_eval.py` |
| 方案质量 | 结构化交付是否可审核、可恢复、可交接 | Replay contract checks |
| 安全 | 注入、无依据承诺、敏感数据 | `make security-check` / `scripts/run_security_checks.py` |
| 微调 | 数据格式、RAG context、target schema、case-level split、hash、token overflow | `make dataset-check` / `make finetune-token-audit` |
| 推理 | TTFT、p95、吞吐、RSS/VRAM、结构化 JSON | Colab notebook + `benchmark_llama.py` |

## 运行命令

```bash
make test
make lint
make eval
PYTHONPATH=src python scripts/run_security_checks.py
make build-finetune-dataset
make dataset-check
make finetune-dry-run
```

## 当前离线证据

在本机依赖环境中，当前 clean-break 基线为：

- Python 单元测试：63 passed（包含需求优先 API、幂等、冲突检测、Replay 分支、原生 interrupt/resume、llama.cpp schema transport 和保守抽取 fallback 测试）。
- 当前 4 条注册 Replay：schema `4/4`、需求门 `4/4`、高风险审核分支 `1/1`；证据存在和无证据保守分支按 `make eval` 的 summary 单独报告。
- 红队策略用例：12/12 通过。
- 当前微调数据：12 条对话，来自 4 条注册 Replay，每个场景最多 3 个变体；train 6、dev 3、test 3，输入包含当前需求优先上下文，target 为紧凑 JSON。
- 当前 Replay 评测索引由 `data/evaluation/manifest.json` 固定来源、版本、hash、许可和敏感级别，并由 `make demo-replay-check` 校验。

此前 24 条案例、72 条对话和 18 条 held-out 的数字属于历史实验记录；它们可以作为 `data/results/` 下的历史证据，但不是当前默认评测或运行时输入。

这些数字证明的是离线契约和规则，不是模型业务准确率，也不是客户生产容量。真正的 LLM 质量报告必须另存 base/adapter、模型 revision、评测提示词、人工评分规则和完整原始输出。

## Colab QLoRA 实测证据

历史实验 commit `095109616c99fe665d296eaab0eebe1b6bd5818b` 在 Tesla T4 上完成了 `compact` model-facing contract 实验。完整的小型摘要报告保存在 [`compact-experiment-20260909.json`](../data/results/colab/qlora/compact-experiment-20260909.json)；adapter 权重和完整运行 bundle 仅保存在 Google Drive，不提交到 GitHub。该报告不作为当前默认数据集或运行时输入。

| 指标 | Base | Adapter | 口径 |
| --- | ---: | ---: | --- |
| JSON parse rate | 100% | 100% | 18 条 held-out synthetic test cases |
| compact schema pass rate | 0% | 77.78%（14/18） | 仅评估 7 字段 model-facing contract |
| policy pass rate | 83.33%（15/18） | 100%（18/18） | 输出策略与敏感信息规则 |
| generation truncated | 0 | 0 | `max_new_tokens=4096`、JSON prefill |

该历史训练运行时为 Qwen2.5-0.5B-Instruct、5 epochs、T4、trainer fp32、compute fp16；训练约 147 秒，峰值 allocated GPU memory 约 2.18 GB。其数据为 24 个合成源案例，train/dev/test=`42/12/18`，token audit 三个 split 均 `over_max_length=0`，base/adapter 使用同一 test split SHA-256。

这个结果支持的结论是：把完整响应拆成“短模型决策对象 + 确定性 Agent/RAG 组装”后，结构化输出和策略通过率显著改善；它不支持“模型在真实业务上达到 77.78% 准确率”或“完整 `SolutionResponseV2` 已由模型端到端可靠生成”。

## 质量门槛建议

上线前至少设置以下门槛，具体阈值由客户黄金集和风险等级决定：

1. 结构化输出解析率 100% 或失败自动进入人工/重试路径。
2. 高风险审核召回率不能以“模型感觉正确”为准，应由规则集和人工抽检共同验证。
3. 无证据时不得出现产品能力、价格、SLA、认证、准确率或容量承诺。
4. adapter 相对 base 的收益必须在保留集和对抗集上同时观察，不能只看训练 loss。
5. 性能报告必须包含失败请求，不得删除慢请求或失败请求后再计算 p95。

生成评估还记录 `generation_truncated`。如果该值较高，先增加生成预算或检查 EOS/chat template；被预算截断的 JSON 不得计入 schema 通过。
