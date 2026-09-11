# Phase 1 API

默认入口是 `scripts/serve_agent.py` 的 FastAPI v2 服务。旧的规则 Agent 和 `http.server` 只作为离线回归 fixture，不提供正式服务入口。

## 启动

```bash
PRESALES_ALLOW_DEV_AUTH=true PRESALES_DEV_TOKEN=dev-token \
  uv run python scripts/serve_agent.py --allow-dev-auth --port 8090
```

`/healthz` 是进程存活检查；`/readyz` 同时检查 checkpoint 数据库、知识索引和 llama-server。`/readyz` 返回 200 `{"status":"ready"}` 或 503 `{"status":"not_ready","checks":{...}}`，前者才允许演示页面创建 Live run。业务接口需要 `Authorization: Bearer <token>`。开发 token 还支持 `X-Tenant-ID`、`X-User-ID`、`X-Roles`，共享部署必须替换成 OIDC/JWT 校验器。

## 资源

| 方法 | 路径 | 最低角色 | 说明 |
|---|---|---|---|
| POST | `/v1/projects/{project_id}/runs` | presales | 创建或按 `Idempotency-Key` 重放 run |
| GET | `/v1/runs/{run_id}` | viewer | 读取脱敏后的状态/响应 |
| GET | `/v1/runs/{run_id}/events` | viewer | 读取节点和审核事件 |
| POST | `/v1/runs/{run_id}/reviews` | reviewer | approve/reject；乐观锁 + 幂等 |
| POST | `/v1/runs/{run_id}/feedback` | presales | 保存评分/标签/反馈 |
| POST | `/v1/chat/completions` | presales | 返回真实 `run_id` 的兼容 facade |

`GET /v1/runs/{run_id}`、创建 run 和审核响应都包含确定性的 `clarify` 投影：

```json
{
  "clarify": {
    "missing_fields": ["deployment", "capacity.peak_concurrency"],
    "questions": ["请确认公有云、私有化、内网还是边缘部署。"]
  }
}
```

该投影只公开缺失字段和澄清问题，不暴露内部 prompt、policy 匹配或完整 Agent 状态。

所有写请求需要 `Idempotency-Key`；服务会返回 `X-Request-ID`。错误使用统一对象：`type`、`title`、`status`、`detail`、`request_id`、可选 `errors`。

## v2 brief

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

`POST /v1/chat/completions` 不绕过鉴权、检索或审核。`choices[0].message.content` 是 v2 JSON 字符串，顶层 `run_id` 可用于查询事件和提交审核。

## 求职演示 Replay

`data/demo/replays/` 保存由 `scripts/capture_demo_replays.py` 从正式 API 捕获的脱敏合成快照。
`scripts/check_demo_replays.py` 不启动模型、不访问网络，只校验案例注册、v2 响应、事件顺序和 Claim—Evidence 引用。

Replay 页面不会调用 `/readyz`、创建 run 或提交审核；高风险案例的“审核通过”只是从 `pending`
快照切换到 `final` 快照，并明确显示“未写入真实运行状态”。
