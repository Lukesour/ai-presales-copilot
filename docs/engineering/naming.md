# 命名规范

## 目的

名称应先表达产品责任，再表达实现细节。读者无需打开文件，就应能判断所有者、行为和边界影响。

创建或重命名符号前，先确认：

1. 功能责任人；
2. 主要责任和 L0-L3 高度；
3. 名称是私有、公共、线协议可见还是持久化字段；
4. 邻近代码和文档已经使用的领域词汇。

## Python 命名

- 包和模块使用小写 `snake_case`，名称应是领域名词或精确角色；
- 类、异常、Pydantic 模型和 protocol 使用 `UpperCamelCase`；
- 函数、方法、变量和属性使用 `lower_snake_case`；
- 常量使用 `UPPER_SNAKE_CASE`；
- 公共类型别名使用能表达领域含义的 `UpperCamelCase`；
- 测试文件按所有者或行为命名，例如 `test_requirements_workflow.py`；
- 测试函数按行为和结果命名，例如 `test_confirmation_is_required_before_retrieval`。

优先使用 `RequirementExtractor`、`EvidencePolicy`、`CheckpointStore`、`LocalModelWorkflow`、`ReviewDecision`、`build_openapi_bundle` 等名称。

## 责任词汇

| 责任 | 优先词汇 |
| --- | --- |
| 确定性规则 | `Policy`、`Invariant`、`Rule`、`Value`、`Identifier` |
| 转换或校验 | `Codec`、`Mapper`、`Parser`、`Validator` |
| 状态或 I/O | `Store`、`Repository`、`Client`、`Cache`、`Index` |
| 产品工作流 | `Workflow`、`UseCase`、`Controller`、`Coordinator` |
| 公共边界 | `Port`、`Contract`、`Adapter`、`Route`、`Dto` |
| 组合或生命周期 | `Factory`、`Registry`、`Scheduler`、`Bootstrap` |

当领域责任可知时，不使用 `Manager`、`Service` 或 `Impl` 代替它。

## 禁止的机械名称

不得新增 `Part1`、`Part2`、`Chunk`、`New`、`Old`、`Legacy`、`Temp`、`Utils`、`Common`、`Shared`、`Misc` 或层编号前缀作为组织名称。

只有确实支持中的兼容行为、且已有明确的移除任务和关闭条件时，才可使用 `Legacy`；本项目 clean-break 后没有项目自有兼容表面。

## 公共、线协议与持久化名称

- OpenAPI operation ID 描述稳定的领域动作，不复制 Python handler 名称；
- 路径描述资源和动作，不暴露实现类；
- Pydantic 字段和 JSON key 必须与 OpenAPI 完全一致；
- 不得仅为代码风格改动公共字段、持久化 key、错误码、fixture ID 或路由；
- 只有真实公共协议版本才允许版本后缀，如 `/v2` 及其线模型；内部类型不要因为关联而全部添加 `V2`；
- Dify/model-facing schema 与持久化模型、UI/session state 分离。

## 函数与状态

- command 使用动词：`confirm_requirements`、`record_feedback`、`schedule_retry`；
- query 描述结果：`pending_events`、`active_checkpoint`；
- 布尔量读起来像谓词：`is_ready`、`has_evidence`、`can_retry`；
- factory 说明创建了什么，不说明“发生了构造”；
- 已知领域概念存在时，避免泛化的 `process`、`handle`、`execute`、`data`、`item`、`result` 和 `value`。

## 脚本、fixture 与文档

- 脚本使用动作加目标：`check_openapi.py`、`capture_demo_replays.py`；
- 迁移使用唯一的下一版本和具体结果，如 `0002_add_checkpoint_format.py`，不使用 `fix_table`；
- fixture ID 说明场景，如 `conflict_or_injection`；
- 文档使用语义责任，如 `knowledge-and-evidence.md`；
- Task ID 发布后保持稳定，改标题不得改 ID。

## Review 清单

- 名称是否表达一个所有者和一个主要责任？
- 领域名词是否比通用技术角色更清楚？
- 是否避免了 L0-L3、顺序或文件大小编码？
- 公共/持久化重命名是否有迁移决策？
- 路由、schema、fixture、任务和文档名称在需要时是否保持稳定？
