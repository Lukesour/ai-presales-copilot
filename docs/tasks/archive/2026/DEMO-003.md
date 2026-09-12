# DEMO-003 — 需求澄清控件可达性修复

Status: Completed  
Owner: Demo and requirements-first owners  
Risk: Boundary  
Completed: 2026-09-12

## Goal

让演示页面能够明确进入并完成 `needs_clarification` 澄清回合，同时保持服务端状态机
对非法澄清请求的 fail-closed 保护。

## Non-goals

- 不允许澄清接口绕过 `needs_clarification` 状态门。
- 不改变 `/v2` 澄清、确认接口或 Replay 快照内容。
- 不把 Replay 快照改造成真实 API 运行结果。

## Root cause

默认 Replay 场景 `normal` 的状态是 `ready_for_confirmation`，因此“提交补充信息”按工作流
契约被置灰；页面此前没有场景选择入口，用户无法从默认快照进入登记的
`missing_then_clarified` 澄清分支。Live API 在真实返回 `needs_clarification` 后的按钮事件
和 `/v2/runs/{run_id}/clarifications` 接口均可正常工作。

## Scope

- 增加 Replay 场景选择器，支持无需重启页面切换到澄清快照。
- 把工作流状态统一投影为按钮交互状态，减少 Gradio 回调中的重复判断。
- 在 `ready_for_confirmation` 时解释为什么澄清按钮禁用，在 `needs_clarification` 时提示可提交。
- 增加状态投影和 Replay 澄清分支回归测试。

## Compatibility policy

服务端仍只允许 `needs_clarification` 状态调用澄清接口；不通过把按钮永久启用来绕过需求门。
Replay 仍只读取登记快照，不发起网络请求、不写入真实运行状态。

## Acceptance

- 默认 `normal` Replay 明确显示当前应确认需求，而不是让用户误以为提交按钮失效。
- 选择 `missing_then_clarified` 后，页面状态为 `needs_clarification` 且“提交补充信息”可用。
- 提交澄清回答后进入 `ready_for_confirmation`，澄清按钮关闭、确认按钮开启。
- Live API 返回 `needs_clarification` 时维持相同交互规则。

## Verification

```text
Live UI: needs_clarification → 提交补充信息 → clarification_turns=1
focused presentation tests: passed
```

## Blockers

无。模型推理耗时和结构化输出质量属于独立运行时风险，不影响本控件状态机修复。
