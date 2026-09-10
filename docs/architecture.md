# Architecture and Design Decisions

## Why one reusable portfolio with layered paths

项目以一个制造业设备运维旗舰案例为主线，分成三个可替换层：

- 应用交付：Dify 或本地 Agent 如何把客户需求、知识检索和方案输出串起来。
- Agent 编排：显式状态、工具白名单、风险门、人工审核和 checkpoint 如何让交付可控。
- 基础设施：同一个模型如何在本地运行，如何测量硬件、量化、上下文和并发对体验的影响。

这些路径共享输入案例、证据资料和结果契约，边界不同：Dify/Agent 负责应用流程与知识使用，llama.cpp/vLLM 负责模型服务与性能，不把基础设施指标伪装成业务准确率。

## Phase 1 data flow

```text
CustomerBriefV2 + auth context
    -> LangGraph intake / clarify / query_rewrite
    -> ACL-filtered retrieval (PostgreSQL tsvector + optional pgvector; local lexical fallback)
    -> local llama-server JSON-Schema draft
    -> evidence grounding + critic + one repair
    -> deterministic security/risk gate
    -> PostgreSQL/SQLite checkpoint + reviewer decision
    -> versioned SolutionResponseV2
```

本地模型运行时的语义生成全部来自 llama-server；字符 n-gram 只作为可审计的 Compose 基线检索器和无模型测试 fixture。没有模型时只返回 `model_unavailable`，不会使用 OfflineSolutionEngine 生成 v2 方案。Dify 适配器仍可用于对照实验，但不绕过 v2 API 的安全硬门。

## Risk boundaries

- 无证据不输出具体产品承诺
- 私有化、数据出域、合规和容量要求进入风险或待确认问题
- 个人演示机器的性能不外推为生产容量
- API Key 只在服务端环境变量中读取
- 文档中的提示词注入内容不拥有更高优先级
- Agent 不拥有任意代码执行、写库、发邮件和生产修改工具
- trace 只记录必要元数据，并在落盘前脱敏

## Compatibility strategy

核心包保留旧 dataclass/HTTP fixture 以便历史评测复现；正式运行时通过锁定的 runtime extra 安装：

- `uv sync --locked --extra runtime` 安装 FastAPI、LangGraph、LangGraph PostgreSQL checkpointer、psycopg 和 Uvicorn。
- SQLite 用于单机测试；Compose 使用项目 checkpoint 表、LangGraph 原生 PostgreSQL `PostgresSaver`、`tsvector` 和 pgvector schema。登记资料通过可选的 `presales-ingest` 一次性任务写入同一知识卷，API 在 SQL 层先做 tenant/ACL/revocation 过滤。
- `mock`/旧 `agent` 路径只用于回归，不应被描述为本地大模型产出的方案。
- Dify 复用 v2 evidence/claim 契约时，需要经过同样的服务端校验。
- 有 CUDA：运行 QLoRA 和 llama.cpp/vLLM 真实实验；无 CUDA 时只报告 dry-run 和已运行的 CPU/Apple 结果。
