# RUNTIME-002 — Live readiness 与本地 checkpoint 启动修复

Status: Completed  
Owner: Runtime and demo owners  
Risk: Boundary  
Completed: 2026-09-12

## Goal

修复本地 Live API 在 llama-server 已健康时仍被 Gradio 阻止的问题，使 checkpoint
格式、模型 identity 和依赖诊断可观察、可执行，并保持不兼容持久化状态 fail closed。

## Non-goals

- 不静默转换、删除或覆盖旧 checkpoint 数据。
- 不改变 `/v2` 需求优先流程、Replay 边界或外部 llama-server `/v1` 协议。
- 不把本地演示结果提升为生产容量或模型质量证据。

## Scope

- persistence readiness：验证数据库可读性和 checkpoint payload format。
- API `/readyz`：区分数据库、知识索引和模型失败，并返回安全诊断码。
- llama.cpp client：同时验证 `/health` 和配置模型是否存在于 `/v1/models`。
- Gradio readiness projection、默认本地 v2 checkpoint 路径、启动文档和回归测试。

## Compatibility policy

旧的无格式标识 checkpoint 保留在原路径并继续被拒绝；新的本地默认路径为当前 v2
checkpoint store。用户可以显式指定旧路径以获得明确的迁移/reset 提示，但系统不做
静默 alias、fallback reader、双写或数据转换。

## Acceptance

- llama-server `/health` 正常但旧 checkpoint 存在时，`/readyz` 返回 503，明确指出
  `checkpoint_format_unsupported`，而不是误报模型未启动。
- 新默认本地 store 在无历史数据时返回 ready，写入的状态带当前 format 标识。
- `/readyz` 能发现配置模型和 llama-server `/v1/models` 不一致。
- Gradio 首屏和“分析需求”反馈包含失败依赖及修复方向；Replay 不发网络请求。
- 不修改旧数据库，保留 clean-break fail-closed 语义。

## Verification

```text
66 pytest tests passed (one existing Starlette deprecation warning)
make governance
make openapi-check
make file-length
make test
make lint
make security-check (12/12)
make demo-replay-check (4 replay manifests)
git diff --check
```

## Blockers

无。真实 llama-server 与现有本地旧数据库仅用于只读复现；模型权重、凭据和运行时
数据库不进入 Git。
