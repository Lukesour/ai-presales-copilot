# DEMO-004 — 澄清输入与提交控件状态一致性修复

Status: Completed  
Owner: Demo and requirements-first owners  
Risk: Boundary  
Completed: 2026-09-12

## Goal

让“需求优先流程”准确表达当前澄清和运行模式状态，避免澄清回答已经提交后仍残留在输入框，
或 Replay 的“未检查 Live API”被误读为服务故障。

## Non-goals

- 不放宽服务端对需求阶段之外状态的校验；Live API 的 `ready_for_confirmation` 补充信息仍须重新评估。
- 不改变 `/v2` 澄清、确认接口、Replay 快照或澄清次数上限。
- 不把 Live API 或模型调用改为 Replay，也不处理真实客户数据。

## Root cause

页面只把工作流状态投影到“提交补充信息”按钮，没有同时投影到输入框；而且澄清输入框
不在回调输出列表中，成功提交后不会被清空。截图中的状态实际是
`ready_for_confirmation`：澄清按钮禁用、确认按钮可用是正确的状态机结果，但保留的旧文本
造成了错误的可操作性暗示。

## Scope

- 让澄清输入框与提交按钮共同受 Live API 的 `needs_clarification` / `ready_for_confirmation` 状态控制；Replay 继续只使用登记快照。
- 成功提交澄清后清空输入框；空提交或 API 失败时保留文本以便修正和重试。
- 为初始渲染设置同样的控件状态，避免页面加载期间出现短暂的错误可操作状态。
- 将 Replay readiness 明确标记为“不适用”，与 Live API 的 readiness 失败区分。
- 增加状态投影回归测试，并以 Replay 真实点击路径验证控件行为。

## Compatibility policy

所有状态变更仍由服务端或登记 Replay 快照产生；UI 只负责投影状态，不自行推断或绕过
需求门。Live API 继续使用状态版本和幂等键提交澄清；Replay 继续不访问网络、不写入真实运行状态。

## Acceptance

- Replay 的 `ready_for_confirmation` 时输入框和提交按钮均不可用，确认按钮可用；Live API 可追加信息并重新评估。
- `needs_clarification` 时输入框和提交按钮均可用，确认按钮不可用。
- 提交成功后状态进入登记的下一快照，输入框清空且提交按钮按新状态门控。
- 失败或空提交不丢失用户输入。
- Replay 模式的 readiness 面板显示“无需 Live API”，不显示为服务失败。

## Verification

```text
full test suite: 71 passed
focused presentation/API/requirements tests: 35 passed
Gradio build smoke check: passed
Playwright UI: missing_then_clarified → submit → ready_for_confirmation,
clarification_turns=1, input cleared and controls re-gated
```

## Blockers

无。Live API readiness 和模型服务属于运行环境前置条件，不是本次控件状态一致性修复的阻塞项。
