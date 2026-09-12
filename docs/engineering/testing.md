# 测试规范

## 测试层次

- 纯策略和 codec 测试覆盖确定性规则及边界不变量；
- 所有者工作流测试覆盖需求、检索、方案、审核和 checkpoint 行为；
- API 测试使用公共 FastAPI seam，断言状态码、错误、鉴权、幂等和 state-version；
- 契约测试比较 OpenAPI、Pydantic 和生成的 Dify/model schema；
- Replay 测试验证不访问网络、数据库或模型的固定合成旅程；
- 安全测试覆盖注入、无依据承诺、敏感数据、租户边界和资源限制。

## 确定性

- 用显式 fake 替换模型 client、clock、网络 transport 和 store；
- 测试不得依赖开发者 `.env`、本地模型权重、在线 Dify、远程 URL 或生产数据库；
- 每个模型 fake 都要清楚表达成功、非法输出和不可用行为；
- 不得用 fixture 掩盖缺依赖，或用 fixture 宣称实时模型质量。

## 命名与 fixture

- 测试文件按所有者或行为命名，不使用 `test_core` 或 `test_utils`；
- 测试函数描述行为和预期结果；
- fixture ID 稳定并说明场景；
- Replay 和评测记录包含 synthetic/source/version/hash 元数据，并标明是否仅检索或允许训练。

## 必须覆盖的回归

- 需求确认前不能检索或生成方案；
- 澄清有上限、可幂等，并拒绝过期 state version；
- 未知 evidence ID、敏感输出、prompt injection 和高风险约束必须 fail closed 或进入审核；
- 审核 approve/reject 可持久化，且不能被另一个幂等键覆盖；
- 不兼容 checkpoint 格式被拒绝，不能自动删除；
- `CLEAN-001` 完成后项目自有 `/v1` 路由、旧 CLI mode 和已删除模块不存在。

## 证据

测试只证明其 scope 中写明的行为。单元测试通过不证明生产可达性、设备行为、外部服务可用性或客户准确率；这些结论需要单独的、有日期且脱敏的证据。
