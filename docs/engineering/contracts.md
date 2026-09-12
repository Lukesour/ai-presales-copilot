# 契约工程规范

## 权威来源

- 手写公共 HTTP 契约：`contracts/openapi/src/`；
- 生成的公共 bundle：`contracts/openapi/dist/`；
- 运行时校验：`src/ai_presales_copilot/schemas.py` 和 transport models 中的 Pydantic 模型；
- Dify/model-facing JSON Schema：从运行时模型生成的快照；
- 行为和失败语义：`docs/api.md`、功能页和 API 测试。

任何第二份文档都不得静默重新定义公共字段、枚举、错误码或路由。

## OpenAPI 规则

- 使用 OpenAPI 3.1 JSON；
- 每个 operation 都有稳定、按领域命名的 `operationId`、请求/响应 schema 和错误响应；
- 显式描述鉴权、租户/项目上下文、`Idempotency-Key`、`state_version`、限流和审核角色；
- 路径使用产品资源和动作，不使用 Python handler 名称；
- `/v2` 是当前项目公共版本，项目不维护自有 `/v1`；
- bundle 必须可由 source 重复生成，禁止手工编辑。

## 变更流程

1. 修改 OpenAPI source 及受影响的组件/路径分片；
2. 同步运行时模型和路由实现；
3. 生成或检查派生 schema；
4. 添加与变更相称的请求、响应、错误和并发回归测试；
5. 更新 API 和功能文档；
6. 执行 `make openapi-check`、聚焦测试和 `git diff --check`。

## Clean-break 规则

当前项目有意移除旧的项目自有兼容行为。不得为已退役的 `/v1` 或完整 Brief 表面新增 alias、回退读取、双写或版本转换。Dify、llama-server 等外部服务仍保留其各自记录的上游协议边界。

## 持久化状态

checkpoint 和数据格式必须带明确格式标识。缺失或不支持的格式必须 fail closed，并返回可执行的 reset/migration 信息。已应用迁移不可修改；表结构变化只能追加唯一版本和明确结果的新迁移。
