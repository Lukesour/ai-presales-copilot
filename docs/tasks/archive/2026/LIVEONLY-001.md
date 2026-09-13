# LIVEONLY-001 — Live API 需求补充与启动链路收口

Status: Completed  
Owner: Runtime and demo owners  
Risk: Boundary  
Completed: 2026-09-13

## Goal

让 Gradio 需求优先流程只面向 Live API 和实时模型：首次分析后的补充信息可以提交，
补充后能够进入 `ready_for_confirmation`，确认后进入真实方案/审核流程；模型不可用或
结构化事实无法验证时明确失败，不使用规则解析或固定模板伪造客户事实。

## Non-goals

- 不删除仓库中用于 CI 契约回归的离线 Replay 快照。
- 不部署外部服务、不接入真实客户数据、不提交模型权重或凭据。
- 不改变 llama-server 的上游 `/v1` 协议或项目公共 `/v2` 兼容边界。

## Scope

旧流程把完整需求 schema 一次交给小模型，并在模型输出失败时使用确定性原文 fallback；长补充文本
会导致字段串位、部署边界被误判为冲突，UI 也容易让用户进入错误模式。当前抽取改为按待补字段分组的
小型 JSON Schema 请求，模型只处理最新客户轮次；主机仅做类型、来源引用、完整性、冲突和状态门校验。
整轮模型失败返回 `model_unavailable`，不生成替代事实。

Gradio 不再暴露模式或场景选择器，单终端启动器负责 llama-server、Presales API 和 Live UI 的
顺序就绪检查，并保持模型 alias 一致。离线 Replay 只保留在测试/评测边界。

## Compatibility policy

保持 `/v2` 请求、状态版本、幂等键和确认门语义；只移除 Gradio 产品页面的 Replay 运行入口。
离线快照仍由 CI 校验，不能接受用户新文本，也不能替代 Live API 的模型质量证据。

## Acceptance

- Live API 首屏显示 `/readyz` 状态和实时模型模式。
- 未创建 run 时补充信息可编辑但提交禁用；首次分析成功后提交按钮启用。
- 初始客户需求和补充信息使用同一个 run，补充后 `blocking_fields=[]` 时进入
  `ready_for_confirmation`，没有重复追问同一字段的死循环。
- 模型/schema/来源校验失败时状态为 `model_unavailable` 或安全停在需求门，无规则解析 fallback。
- 确认后只调用 Live API 方案节点；高风险结果进入真实 `waiting_for_review`。

## Verification

`make test`、`make lint`、`make openapi-check`、`make schema-check`、`make demo-replay-check`、
`make security-check`、`make lock-check`、`make file-length` 和 `git diff --check`；本机还用真实
llama-server、Presales API、Gradio 和 Playwright 验证了客户原始需求 → 补充信息 →
`ready_for_confirmation` → `waiting_for_review` 的路径。

## Blockers

无。本地演示仍要求 `uv`、`llama-server` 和合法 GGUF 文件；生产环境仍需经过授权的身份、密钥、
日志、模型供应链和容量方案。
