# Phase 1 API

默认入口是 `scripts/serve_agent.py` 的 FastAPI v2 服务。项目公共 HTTP 契约由 `contracts/openapi/src/` 维护，`contracts/openapi/dist/` 是生成 bundle。

## 启动

```bash
PRESALES_ALLOW_DEV_AUTH=true PRESALES_DEV_TOKEN=dev-token \
  uv run python scripts/serve_agent.py --allow-dev-auth --port 8090
```

`/healthz` 是进程存活检查；`/readyz` 同时检查 checkpoint 数据库、知识索引和 llama-server。模型检查不仅访问 llama-server `/health`，还核对 `/v1/models` 是否包含 API 配置的模型。`/readyz` 返回 200 `{"status":"ready"}` 或 503 `{"status":"not_ready","checks":{...}}`，前者才允许演示页面创建 Live run。失败时 `checks` 会保留安全的 `*_error_code` 和必要诊断；例如 `checkpoint_format_unsupported` 要求保留旧库并使用显式迁移或 clean reset，不会静默转换。业务接口需要 `Authorization: Bearer <token>`。开发 token 还支持 `X-Tenant-ID`、`X-User-ID`、`X-Roles`，共享部署必须替换成 OIDC/JWT 校验器。

## 资源：需求优先 v2

正式入口只有 `/v2`；项目不注册自有 `/v1` 路由。Dify `/v1/chat-messages` 和 llama-server `/v1/chat/completions` 是外部服务协议，由各自 adapter 调用。

| 方法 | 路径 | 最低角色 | 说明 |
|---|---|---|---|
| POST | `/v2/projects/{project_id}/runs` | presales | 只接收 `input.raw_request`，创建需求分析 run |
| POST | `/v2/runs/{run_id}/clarifications` | presales | 追加最多 3 个澄清回合，重新抽取和评估 |
| POST | `/v2/runs/{run_id}/requirements/confirm` | presales | 确认关键需求和警告假设后进入方案图 |
| GET | `/v2/runs/{run_id}` | viewer | 读取原始输入、brief、字段事实、完整性分析和响应 |
| GET | `/v2/runs/{run_id}/events` | viewer | 读取需求门、方案节点和审核事件 |
| POST | `/v2/runs/{run_id}/reviews` | reviewer | approve/reject；乐观锁 + 幂等 |
| POST | `/v2/runs/{run_id}/feedback` | presales | 保存评分/标签/反馈 |
| POST | `/v2/chat/completions` | presales | 进入同一需求优先状态机的兼容 facade |

所有写请求需要 `Idempotency-Key`；澄清、确认、审核和反馈还必须携带响应中的 `state_version`（澄清/确认也接受别名 `expected_state_version`）。版本过期返回 `409`，同一幂等键返回之前的投影。澄清单回合最多 4 个问题，run 最多 3 个澄清回合。

初始请求示例：

```json
{
  "input": {
    "raw_request": "客户希望把维修手册和历史工单做成设备运维知识助手，回答必须可引用。",
    "source": "meeting_notes",
    "locale": "zh-CN"
  },
  "source": "meeting_notes"
}
```

需求阶段公开状态示例：

```json
{
  "status": "needs_clarification",
  "phase": "requirements",
  "brief": {"business_goal": null, "deployment": null},
  "requirement_analysis": {
    "blocking_fields": ["business_goal", "deployment", "acceptance_criteria"],
    "warning_fields": ["capacity.peak_concurrency"],
    "questions": []
  },
  "response": null
}
```

`RequirementFactV2` 的 `status` 区分 `stated`、`confirmed`、`inferred`、`missing`、`ambiguous`、`conflicting`；`stated/confirmed` 必须带 `source_turn_id` 和服务端验证过的 `source_quote`。完整性目录由代码计算，模型不能自行把推断值升级为客户事实。

需求状态还会返回 `extraction_mode`：正常为 `model`；本地模型或 schema 失败后若能从原文安全匹配则为 `deterministic_fallback`。后者只生成带原文片段的保守需求事实，仍停在 `needs_clarification` 或 `ready_for_confirmation`，不会检索或生成方案。方案节点的结构化输出失败仍进入 `model_unavailable`，不会用固定模板补齐。

## 项目边界

所有写请求需要 `Idempotency-Key`；服务会返回 `X-Request-ID`。错误使用统一对象：`type`、`title`、`status`、`detail`、`request_id`、可选 `errors`。旧项目模型、旧 fixture 和旧 HTTP 路由不提供转换或回退读取。

## 方案输出 brief（确认后内部契约）

```json
{
  "schema_version": "2.0",
  "case_id": "manufacturing-001",
  "industry": "制造业",
  "use_case": "设备运维知识助手",
  "deployment": "私有化",
  "capacity": {
    "peak_concurrency": 5,
    "daily_requests": 1000,
    "ttft_target_ms": 2000,
    "full_answer_target_ms": 10000
  },
  "governance": {
    "data_classification": "内部",
    "residency": "中国境内",
    "egress_allowed": false,
    "audit_required": true,
    "allowed_roles": ["presales", "reviewer"]
  },
  "raw_request": "请给出可引用、可审计的设备故障问答 POC。"
}
```

响应包含 `claims[]`、`evidence[]`、`review`、`provenance` 和 `quality`。支持的事实 claim 必须有真实 evidence ID；模型引用不存在的 ID 会被丢弃并触发审核。

## OpenAI-compatible facade

`POST /v2/chat/completions` 不绕过鉴权、检索或审核。`choices[0].message.content` 是 v2 JSON 字符串，顶层 `run_id` 可用于查询事件和提交审核。

## 求职演示 Replay

`data/demo/replays/` 保存由 `scripts/capture_demo_replays.py` 从正式 API 捕获的脱敏合成快照。
`scripts/check_demo_replays.py` 不启动模型、不访问网络，只校验案例注册、v2 响应、事件顺序和 Claim—Evidence 引用。

Replay 页面不会调用 `/readyz`、创建 run 或提交审核；高风险案例的“审核通过”只是从 `pending`
快照切换到 `final` 快照，并明确显示“未写入真实运行状态”。
