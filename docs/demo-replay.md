# Demo Replay 契约

## 目的

`Demo Replay` 是求职演示的稳定展示路径。它读取仓库内预先捕获的合成 JSON，不调用模型、数据库、FastAPI 或 `/readyz`。Replay 保存的是完整输入驱动过程，不只是最终方案。
它不是 LangGraph checkpoint time travel：后者会重新执行检查点之后的节点，可能再次调用 LLM、API 或 interrupt。

## 文件和校验

- 案例注册：`data/demo/scenarios.json`
- 快照目录：`data/demo/replays/`
- 契约与加载器：`src/ai_presales_copilot/demo_replay.py`
- 纯展示投影：`src/ai_presales_copilot/demo_view.py`
- 控制器：`src/ai_presales_copilot/demo_controller.py`
- 离线校验：`scripts/check_demo_replays.py`
- 数据来源与 hash manifest：`data/evaluation/manifest.json`
- 正式 API 捕获：`scripts/capture_demo_replays.py`

运行：

```bash
make demo-replay-check
```

校验内容包括：

1. 必须注册 `normal`、`missing_then_clarified`、`high_risk`、`conflict_or_injection` 四条需求优先主分支；
2. 每个快照必须是 `replay_schema_version=1.0`、`synthetic=true`、`captured_from=live_api`；
3. `states.final.response` 必须通过 `SolutionResponseV2`；
4. Claim 的事实引用必须存在于 evidence；
5. 事件 `seq` 必须从 1 连续递增；
6. 需求优先主分支必须有 `initial_input`、`input_turns` 和无 response 的初始需求状态；
7. 正常、补充后和高风险分支中，`requirements_confirmed` 事件必须发生在 `retrieve/draft/finalize` 之前；
8. `conflict_or_injection` 不得包含检索、草案或完成事件；
9. `high_risk` 必须同时包含 `pending` 和 `final`，且前者为 `waiting_for_review`；
10. 快照不能包含 Authorization、API Key、邮箱、手机号、身份证、密钥等敏感信息。
11. 评测索引、场景目录和四份 Replay 的来源、版本、hash、许可和敏感级别必须通过 manifest 校验。

## 审核回放语义

Replay 的初始展示优先使用 `states.initial`；澄清回合切换到 `states.clarified`，确认后切换到 `states.confirmed` 之后的 `pending` 或 `final`。高风险 Replay 点击“人工审核通过”只在当前 Gradio 会话中把状态切换到 `states.final`，并显示：

```text
当前为静态回放，已切换到审核通过快照，未写入真实运行状态。
```

因此回放可以稳定证明“人工审核前后状态不同”，但不能被描述为真实生产审批记录。

首屏只展示默认的 `normal` 合成原始需求，不提供场景下拉框或辅助示例按钮。离线验收仍可通过
`PRESALES_REPLAY_CASE=missing_then_clarified`、`high_risk` 或 `conflict_or_injection` 在启动前选择登记分支；
这只是测试/演示配置，不是新的正式输入契约。
