# RUNTIME-003 — Live API 需求澄清按钮不可用

Status: Completed  
Owner: Runtime and demo owners  
Risk: Boundary  
Completed: 2026-09-12

## Goal

在 Live API 模式下，客户输入不完整需求后稳定进入 `needs_clarification`，并使“提交补充信息”
在该状态可编辑、可提交；进入 `ready_for_confirmation` 后仍允许客户追加新增信息，补充信息被幂等地
追加到同一个 run、重新评估并要求再次确认，而不是把按钮永久放开或绕过需求门。

## Non-goals

- 不改变 `/v2` HTTP 路径、请求字段、鉴权、幂等键或 `state_version` 语义。
- 不允许模型自行决定是否可以生成方案。
- 不把 Replay 变成 Live API，也不提交模型权重、客户数据或本地凭据。
- 不允许补充信息绕过再次确认；在 `ready_for_confirmation` 状态提交后必须重新评估并再次确认。

## 根因证据

1. UI 控件原先只把 `needs_clarification` 映射为可提交，`ready_for_confirmation` 只启用确认按钮；
   这与用户主动追加需求的 Live API 诉求不一致。直接只改 UI 又会被 API 的状态冲突保护拒绝。
2. 用户原始启动命令未显式指定 `--model`。`serve_agent.py` 默认使用 `qwen3-8b-q4`，
   而 llama-server 使用 `--alias qwen3-1.7b-demo`，因此 `/healthz` 可为 200，但 `/readyz`
   因 `model_mismatch` 为 503，Live 页面在创建 run 前被正确阻断。
3. 旧的需求抽取 schema 要求小模型同时生成完整 nullable brief、facts、conflicts 和 assumptions，
   并允许 `max_tokens=2048`。在 Qwen3 1.7B 本地运行中出现超过两分钟的结构化生成、截断或字段幻觉，
   从而延迟状态切换或触发整轮 fallback。
4. 原实现对单条错误的 `source_quote` 采用整轮失败策略；小模型把整段补充文本误标为
   `integrations` 时，合法的业务目标、用户、部署和验收事实也会一起丢失。
5. 本地曾同时存在多个 Gradio 进程，旧页面占用 7860、新页面自动占用 7861；用户若继续打开旧地址，
   会看到旧会话和旧代码的控件状态。这是运行方式问题，不是新增网页入口。

## Scope

- 将 model-facing `brief` 收敛为 `schema_version`、`case_id`；客户字段只通过有限字段目录中的
  source-attributed facts 传输。
- 将需求抽取的上限从 2048 收敛为 768 tokens；保留一次有界结构化重试和主机端 Pydantic 校验。
- 由主机根据 `stated`/`confirmed` 且引用合法的 facts 重建 `IntakeBriefV2`；模型不能用第二份 brief
  覆盖客户事实， readiness 仍由 `assess_requirements` 确定性计算。
- 对 malformed model fact 逐条隔离：错误归因降级为无值 `ambiguous`，不进入 brief；其余 facts 继续处理。
- 合并确定性高置信原文匹配，覆盖本地小模型常见的中文目标用户、部署、数据驻留、业务目标和验收模式。
- 支持中文顿号列表和 `capacity.latency_target` 到 `full_answer_target_ms` 的明确映射，避免澄清覆盖再次失败。
- 保留 UI 的状态门：Live API 在 `needs_clarification` 和 `ready_for_confirmation` 启用“提交补充信息”；
  成功后重新评估、清空输入并按新状态门控；Replay 仍只允许登记的澄清快照。

## Compatibility policy

公共 `/v2` 合同不变。Live 本地演示必须使用同一模型身份：

```text
llama-server ... --alias qwen3-1.7b-demo
serve_agent.py ... --model qwen3-1.7b-demo
PRESALES_INITIAL_MODE=live gradio_app.py --mode api --initial-mode live
```

启动后先检查 `GET http://127.0.0.1:8090/readyz` 为 200，且 `checks.model=true`；浏览器只打开
Gradio 进程实际打印的唯一页面地址。若需要直接进入 Live API，必须使用上述显式初始模式；默认 Replay
仍是安全的离线模式。

## Acceptance

`needs_clarification` 时补充输入和按钮可用；Live API 在 `ready_for_confirmation` 也可追加信息，
提交后重新评估；只有 `requirements/confirm` 才能进入方案图，服务端拒绝其他状态的补充请求。

## Verification

- `tests/test_requirements_first.py`、`tests/test_v2_runtime.py` 和 `tests/test_demo_presentation.py`：
  需求门、引用隔离、Live 控件状态和 API 澄清流通过。
- 真实本地链路：不完整输入进入 `needs_clarification`；提交补充信息后进入
  `ready_for_confirmation`，blocking fields 为空；在 ready 状态再次提交补充信息后仍完成重新评估，
  不返回状态冲突。
- Playwright 浏览器验证：Live API + 唯一的 `http://127.0.0.1:7860/` 下，需求不完整时和 ready
  状态下“提交补充信息”均可点击；ready 状态提交后输入被清空、按钮仍按新状态门控，确认按钮保持可点击。
- 仓库门禁：`make test`（75 passed）、`make lint`、`make governance`、`make demo-replay-check`、
  `make openapi-check`、`make security-check`、`make file-length`、`git diff --check` 已通过。

## Blockers

Qwen3 1.7B 仍不是生产级需求抽取质量证据；当前实现通过确定性门、引用校验和保守缺失字段策略
保证不因模型幻觉直接进入方案生成。生产/共享环境仍需真实身份、模型供应链、容量和观测证据，不能由本地
演示结果推断。
