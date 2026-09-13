# DEMO-005 — Live API 补充信息输入可达性修复

Status: Completed  
Owner: Demo and requirements-first owners  
Risk: Boundary  
Completed: 2026-09-12

## Goal

让用户启动 Gradio 后能明确区分 Replay 与 Live API，并在 Live API 首次分析前可以在“补充信息”框中
输入草稿；需求分析完成后，只有需求门允许的状态才能提交补充信息。

## Non-goals

- 不允许 Replay 接收任意客户输入或写入 Live API。
- 不允许已确认、已进入方案阶段或模型失败的 run 继续追加补充信息。
- 不改变 `/v2` HTTP 路径、鉴权、幂等键、状态版本或服务端需求门。

## 根因证据

1. `gradio_app.py --mode api` 只表示页面通过正式 API 边界运行，并不代表 UI 初始选择了 Live API；页面
   默认选中 Replay。默认 `normal` 快照为 `ready_for_confirmation`，Replay 在该状态按契约禁用补充输入。
2. 用户启动第二个 llama-server、Presales API 和 Gradio 实例时，8080、8090 已被旧进程占用，Gradio
   自动转到 7861，增加了打开旧页面或误判运行模式的概率。
3. 需求补充输入依赖已有 run；此前 Live 初始状态没有 run 时输入框也被禁用，但页面没有明确解释“先分析
   原始需求”的前置步骤。
4. 用户时间线已经从需求确认进入 `query_rewrite`、`retrieve` 和 `draft`；此时 run 已离开需求门，`draft`
   的 `model_unavailable` 不能通过补充输入回退到需求阶段。

## Scope

- 增加 `PRESALES_INITIAL_MODE=live` / `--initial-mode live`，保留 Replay 的安全默认值。
- Live 尚未创建 run 时允许补充框输入草稿，但不启用提交按钮；首次分析后按状态门控。
- 切换模式或 Replay 场景时清空旧补充草稿，避免跨模式误提交。
- 对空状态和 `model_unavailable` 展示下一步可执行提示。
- Gradio 固定默认端口并在端口被占用时失败，避免静默切换 7861 造成旧页面/新页面混淆。
- 增加控制状态、提示文案和 Gradio 构建回归测试。

## Compatibility policy

服务端仍是最终授权者：只有 `needs_clarification` 或 Live 的 `ready_for_confirmation` 接受补充请求；
UI 的草稿可编辑性不代表允许创建或修改 run。默认 Replay 不发起网络请求；Live 初始模式只检查 readiness，
不会在用户点击“分析需求”前创建 run。

## Acceptance

- 默认启动仍显示 Replay，且 Replay 的补充框保持不可编辑。
- 使用 `PRESALES_INITIAL_MODE=live` 或 `--initial-mode live` 启动时，页面选中 Live API，`/readyz` 通过后
  可在首次分析前输入补充草稿。
- 首次分析完成后，`needs_clarification` 和 `ready_for_confirmation` 可提交；运行中、已确认、方案阶段和
  `model_unavailable` 不可提交。
- 方案阶段模型失败时，页面明确提示修改原始需求并重新分析创建新 run。
- 端口冲突会在固定端口启动时明确失败；启动文档要求先处理旧进程，或显式指定新端口并使用实际打印的唯一页面地址。

## Verification

- Playwright 复现：7861 首屏明确为 Replay；切换 Live 并分析后，补充框可输入；提交前草稿可保留。
- 单元回归：Live 无 run 输入可编辑但提交禁用；Live ready 可提交；Replay ready 禁用；model unavailable
  提示重新分析。
- `make test`、`make lint`、`make governance`、`make demo-replay-check`、`make openapi-check`、
  `make security-check`、`make file-length`、`git diff --check`。

## Blockers

无。Qwen3 1.7B 的方案阶段结构化输出仍可能进入 `model_unavailable`，这是模型能力/运行时问题；本任务只
确保该失败状态可诊断且不让用户误以为补充输入可以修改已确认 run。
