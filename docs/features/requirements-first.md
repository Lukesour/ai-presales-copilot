# 需求优先方案流程

## 责任域

`src/ai_presales_copilot/requirements.py`, `llm_agent.py`, `api_v2.py` and the related
Pydantic 契约负责需求优先工作流。

## 行为

```text
raw input
  -> intake
  -> extract_requirements
  -> assess_requirements
  -> clarify / confirmation
  -> query_rewrite
  -> retrieve
  -> draft
  -> ground_claims
  -> critic / repair
  -> risk_gate
  -> human_review / finalize
```

系统保存输入轮次、字段事实、原文引用、冲突和状态版本。阻断字段缺失或冲突时停止检索和方案生成。
需求确认是进入方案图的唯一入口。

## 契约

项目自有 API 是 `/v2`。写请求必须携带 `Idempotency-Key`；澄清、确认、审核和反馈使用乐观
`state_version` 检查。高风险、敏感、无依据或涉及注入的输出进入审核或 fail closed。

## 证据

- `docs/agent-design.md`
- `docs/api.md`
- `docs/phase1-acceptance.md`
- `tests/test_requirements_first.py`
- `tests/test_v2_runtime.py`
