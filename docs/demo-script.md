# 求职演示脚本（约三分钟）

## 启动前检查

先运行离线契约检查：

```bash
make demo-replay-check
```

如果要演示 Live API，使用单终端启动器：

```bash
uv sync --locked --extra runtime --extra demo
PRESALES_DEV_TOKEN=dev-token \
  uv run --locked --extra runtime --extra demo python scripts/start_local_demo.py
```

也可以使用等价入口 `make demo-live`。

启动器先等待 llama-server 的 `/v1/models` 暴露 `qwen3-1.7b-demo`，再等待 Presales API
的 `/readyz` 返回 200，最后启动 Gradio；默认页面是 `http://127.0.0.1:7860`。它固定端口，
不会像 Gradio 默认行为一样自动切到 7861；端口冲突时应先关闭旧进程或显式覆盖三个端口。
按 `Ctrl-C` 会清理启动器创建的三个子进程。若本机已有旧 `.runtime/agent/checkpoints.db`，
当前 API 默认使用新的 v2 checkpoint 路径；旧库不会被删除或静默转换。

用户演示只使用 Live API：启动器检查 `/v1/models` 和 `/readyz`，任一依赖未就绪就不启动可交互流程。
Live 尚未创建 run 时，补充信息框允许先输入草稿，提交按钮要等首次需求分析完成后才启用；没有规则解析或 Replay 兜底。

## 0:00–0:20：输入客户原始需求

“售前方案不能从预填 Brief 或辅助示例开始。我先粘贴客户原始需求，让系统判断现在是否具备做方案的条件。”

展示大文本框和“分析需求”。强调：Live 使用 `/v2/projects/{project_id}/runs` 创建真实需求分析 run；模型未就绪时请求会被 readiness 闸门阻止。

## 0:20–0:50：需求解析和缺口分析

在“需求优先流程”展示：

- `IntakeBriefV2` 的 `null` 缺失值；
- `RequirementFactV2` 的状态、置信度、来源轮次和原文引用；
- 阻断字段、警告字段、冲突和最多四个澄清问题。

说明：完整性由服务端字段目录确定，模型不能把 `inferred` 静默升级为客户事实。

## 0:50–1:20：补充信息和需求确认

在 Live 页面粘贴客户补充信息，点击“提交补充信息”，展示：

```text
initial_input → extracted_requirements → needs_clarification
              → clarification_answer → ready_for_confirmation → confirmed
```

点击“确认需求并生成方案”，说明关键字段未确认时不存在 `retrieve/draft/finalize` 事件；澄清和确认都使用同一个 run、幂等键和 state version。

## 1:20–1:45：方案和 POC

打开“方案交付”，展示带 evidence ID 和来源定位的 Claim、架构、实施步骤，以及 POC 的 objective、activities、deliverables 和 exit criteria。QLoRA、Dify 和部署选型只作为确认后的技术附录。

## 1:45–2:20：高风险审核

若需要展示高风险分支，在 Live 输入中明确数据出域和审计要求，确认需求后展示：

```text
requirements_confirmed → retrieve → ... → pending_review → approve → final
```

说明数据不能出域和审计要求为什么触发审核；审核调用正式 Live API，不切换静态快照。

## 2:20–2:50：证据与拒绝分支

打开“证据追溯”：一个 Claim 对应多个 evidence 时拆成多行；没有证据的事实转成 `unknown/needs_review`，不输出产品承诺。

若需要展示拒绝分支，在 Live API 中输入互相冲突或包含提示词注入的客户原文，展示输入被阻断，
且没有检索、草案和最终方案事件；不要切换到离线回放。

## 2:50–3:00：边界说明

“这是求职演示：案例和资料是合成的，离线契约快照和单机基准不等于生产 SLA。生产化还需要 OIDC/JWT、目标硬件容量测试、真实数据治理和企业连接器。主线证明的是从客户原话到可追溯方案的闭环。”

## 快照维护

只有正式 API 和模型就绪时才捕获新快照：

```bash
PYTHONPATH=src:. uv run --locked --extra runtime --extra dev python scripts/capture_demo_replays.py --api-url http://127.0.0.1:8090 --force
make demo-replay-check
```

快照文件不能手写 Authorization、API Key、真实客户资料或敏感字段。高风险快照必须同时保存审核前的 `pending` 和审核后的 `final`。
