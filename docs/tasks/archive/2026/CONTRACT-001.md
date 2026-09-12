# CONTRACT-001 — OpenAPI-first 公共契约

Status: Completed  
Owner: API and contract owner  
Risk: Boundary  
Completed: 2026-09-11

## 目标

让当前需求优先 `/v2` HTTP 表面显式、可复现，并与 FastAPI 和 Pydantic 的实现行为持续校验。

## 非目标

- 不记录项目自有 `/v1` 兼容行为。
- 不把 Dify 或 llama-server 上游协议变成项目自有契约。
- 不引入生成式客户端代码。

## 范围

`contracts/openapi/src/`、生成的 `dist/`、路由/组件分片、OpenAPI 构建/检查脚本、schema 导出
检查、API 测试和 API 文档。

## 兼容策略

手写 OpenAPI source 是公共 HTTP 行为的权威；bundle 和 Dify/model schema 是生成或校验产物。
项目自有不兼容 `/v1` 行为直接删除，不增加 alias 或回退读取。

## 验收

- 所有 `/v2` 和运维路由都有稳定 operation ID，并显式描述错误、鉴权、状态版本和审核语义。
- 引用可解析且 OpenAPI 结构校验通过。
- 路由清单和 Pydantic 字段/枚举检查通过。
- Dify/model schema 快照可生成并通过漂移检查。
- 项目自有 `/v1` 路由不存在。

## 验证

```bash
make openapi-build
make openapi-check
make schema-check
make test
```

## 阻塞项

本任务无阻塞。后续公共行为必须以新的契约变更、测试和文档一起交付。
