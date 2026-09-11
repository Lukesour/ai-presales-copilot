# Demo Replay 契约

## 目的

`Demo Replay` 是求职演示的稳定展示路径。它读取仓库内预先捕获的脱敏 JSON，不调用模型、数据库、FastAPI 或 `/readyz`。
它不是 LangGraph checkpoint time travel：后者会重新执行检查点之后的节点，可能再次调用 LLM、API 或 interrupt。

## 文件和校验

- 案例注册：`data/demo/scenarios.json`
- 快照目录：`data/demo/replays/`
- 契约与加载器：`src/ai_presales_copilot/demo_replay.py`
- 纯展示投影：`src/ai_presales_copilot/demo_view.py`
- 控制器：`src/ai_presales_copilot/demo_controller.py`
- 离线校验：`scripts/check_demo_replays.py`
- 正式 API 捕获：`scripts/capture_demo_replays.py`

运行：

```bash
make demo-replay-check
```

校验内容包括：

1. 必须注册 `normal`、`missing`、`high_risk` 三个场景；
2. 每个快照必须是 `replay_schema_version=1.0`、`synthetic=true`、`captured_from=live_api`；
3. `states.final.response` 必须通过 `SolutionResponseV2`；
4. Claim 的事实引用必须存在于 evidence；
5. 事件 `seq` 必须从 1 连续递增；
6. `high_risk` 必须同时包含 `pending` 和 `final`，且前者为 `waiting_for_review`；
7. 快照不能包含 Authorization、API Key、邮箱、手机号、身份证、密钥等敏感信息。

## 审核回放语义

高风险 Replay 初始展示 `states.pending`。点击“人工审核通过”只在当前 Gradio 会话中把状态切换到 `states.final`，并显示：

```text
当前为静态回放，已切换到审核通过快照，未写入真实运行状态。
```

因此回放可以稳定证明“人工审核前后状态不同”，但不能被描述为真实生产审批记录。
