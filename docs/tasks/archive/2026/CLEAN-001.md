# CLEAN-001 — 项目兼容面 clean-break

Status: Completed  
Owner: Runtime and evaluation owners  
Risk: Boundary  
Completed: 2026-09-11

## 目标

移除项目自有的退役 HTTP、dataclass、规则 Agent、fixture 和 schema 兼容路径，使需求优先
`/v2` 流程成为唯一项目公共基线。

## 非目标

- 不删除外部 Dify 或 llama-server provider endpoint。
- 不重写历史基准报告，除非活跃脚本仍读取它们。
- 不自动删除旧 checkpoint 数据库或用户文件。

## 范围

删除 v1 路由、旧 `api.py`、规则 Agent/offline engine/LangGraph adapter、退役 dataclass
转换函数、旧 CLI fixture 模式、旧 fixture/schema 文件和旧读取器。仍有责任的 Dify、评测和
数据脚本迁移到当前 v2 契约；无责任的路径直接删除。

## 兼容策略

不增加 alias、fallback reader、双写或静默 checkpoint 转换。不兼容 checkpoint 必须 fail
closed，并给出 clean reset 或 migration 信息。外部 provider 的 `/v1` 路径仍是上游边界，
不是项目自有路由。

## 验收

- 活跃项目代码不再导入退役模块或 dataclass。
- 项目自有 `/v1` 路由未注册，且不会成功响应。
- 当前 Replay 分支和 v2 API 测试仍有效。
- 旧 CLI 参数、fixture 文件和生成 schema 已删除或明确标为历史证据。
- 活跃评测和微调读取器只消费当前 v2 记录。

## 验证

```bash
make test
make demo-replay-check
make openapi-check
if rg -n '(/v1/projects|/v1/runs|from_legacy|to_legacy|OfflineSolutionEngine|PresalesAgent|AgentHTTPService|--mode fixture|missing\.json|output_schema\.json)' src scripts tests demo data dify; then exit 1; fi
```

## 阻塞项

本任务无阻塞。历史报告仅作为 evidence；不兼容 checkpoint 需要经明确批准的本地 reset 或
migration，系统不会自行删除或转换。
