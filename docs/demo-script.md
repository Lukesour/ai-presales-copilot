# 求职演示脚本（约三分钟）

## 启动前检查

先运行离线契约检查：

```bash
PYTHONPATH=src python scripts/check_demo_replays.py
```

如果要演示 Live API，再启动 FastAPI、PostgreSQL/SQLite checkpoint 和 llama-server：

```bash
PRESALES_ALLOW_DEV_AUTH=true PRESALES_DEV_TOKEN=dev-token \
  uv run python scripts/serve_agent.py --allow-dev-auth --port 8090
```

打开页面：

```bash
uv sync --locked --extra demo
PRESALES_API_TOKEN=dev-token uv run python demo/gradio_app.py --mode api
```

页面默认是 `Live API`。如果 `/readyz` 未就绪，直接切换 `Demo Replay`，不会影响完整讲解。

## 0:00–0:20：问题和 readiness

“售前方案通常遇到三个问题：客户约束不完整、产品事实难追溯、高风险结论缺少审核。我把它们放进一个结构化、可恢复的 Agent 流程里。”

展示顶部 `/readyz`：

- `/healthz` 只说明 API 进程存活；
- `/readyz` 检查数据库、知识索引和模型；
- 未就绪时 Live 生成不会发送创建 run 请求，Replay 仍可用。

## 0:20–1:05：正常方案与完整 v2 输出

选择 `正常方案 · normal`，点击“生成方案”。在“方案总览”依次展示：

- 页面顶部的完整 `CustomerBriefV2`：行业、场景、数据类型、部署、容量、治理、预算、集成和验收标准；
- 执行摘要、结构化需求、建议、架构、实施步骤；
- POC 的 objective、activities、deliverables、exit criteria；
- 完整 `model_strategy`、假设、澄清问题、审核、provenance 和 quality。

强调：页面不是只展示一段自然语言，而是把 `SolutionResponseV2` 的 17 个主要字段逐个投影出来；原始 JSON 只放在折叠区域。

## 1:05–1:35：Agent 时间线

打开“Agent 时间线”：

```text
intake → clarify → query_rewrite → retrieve → draft → ground_claims
      → critic → repair → risk_gate → human_review → finalize
```

说明：时间线来自 `GET /v1/runs/{run_id}/events`，Live 和 Replay 使用同一套纯渲染函数。
没有执行的 `repair` 仍显示“未执行”；没有可靠耗时的位置显示 `—`，不虚构性能数据。

## 1:35–2:00：Claim—Evidence 追溯

打开“证据追溯”：

- 一个 Claim 对应多个 evidence 时拆成多行；
- 每行展示支持状态、证据 ID、来源、版本、页码、locator、hash 和摘要；
- 没有证据的 Claim 显示 `—`，`unknown`/`needs_review` 保留醒目标记；
- 事实型 Claim 的 evidence ID 在 API 和 Replay 加载时都会校验。

“因此模型只负责提出受约束的文本，事实绑定、权限和风险门由确定性代码控制。”

## 2:00–2:20：信息缺失案例

切换 `信息缺失 · missing` 并加载 Replay，展示 `clarify.missing_fields`：

```text
deployment
capacity.peak_concurrency
capacity.latency_target
governance.residency
```

说明：系统不会因为缺少部署、容量和合规信息就猜测云端、本地或 SLA，而是生成澄清问题。

## 2:20–2:45：高风险审核案例

切换 `高风险需审核 · high_risk`，展示：

```text
waiting_for_review → approve → complete
```

在“风险审核”中解释数据不能出域、审计要求和高风险动作。点击“人工审核通过”：

- Live 模式调用正式审核 API，并重新读取 run/events；
- Replay 模式只切换到已捕获的 `final` 快照；
- 页面明确标记 Replay 未写入真实运行状态。

## 2:45–3:00：边界说明

“这个版本是求职演示：案例和资料是合成的，Replay 是静态快照，离线评测和单机基准不等于生产 SLA。生产化还需要 OIDC/JWT、目标硬件容量测试、真实数据治理和企业连接器。当前演示重点是把需求、证据、Agent 状态和人工审核串成可解释的交付闭环。”

## 快照维护

只有正式 API 和模型就绪时才捕获新快照：

```bash
PYTHONPATH=src python scripts/capture_demo_replays.py --api-url http://127.0.0.1:8090 --force
PYTHONPATH=src python scripts/check_demo_replays.py
```

快照文件不能手写 Authorization、API Key、真实客户资料或敏感字段。高风险快照必须同时保存审核前的 `pending` 和审核后的 `final`。
