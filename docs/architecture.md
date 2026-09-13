# Architecture and Design Decisions

## Why one reusable portfolio with layered paths

项目以一个制造业设备运维旗舰案例为主线，分成三个可替换层：

- 应用交付：Dify 或本地 Agent 如何把客户需求、知识检索和方案输出串起来。
- Agent 编排：显式状态、工具白名单、风险门、人工审核和 checkpoint 如何让交付可控。
- 基础设施：同一个模型如何在本地运行，如何测量硬件、量化、上下文和并发对体验的影响。

这些路径共享输入案例、证据资料和结果契约，边界不同：Dify/Agent 负责应用流程与知识使用，llama.cpp/vLLM 负责模型服务与性能，不把基础设施指标伪装成业务准确率。

## Phase 1 data flow

```text
CustomerInputV2(raw_request) + auth context
    -> intake / extract_requirements / assess_requirements
    -> clarify OR requirements_confirmation
    -> LangGraph query_rewrite / retrieve / draft
    -> ACL-filtered retrieval (PostgreSQL tsvector + optional pgvector; local lexical fallback)
    -> local llama-server JSON-Schema draft
    -> evidence grounding + critic + one repair
    -> deterministic security/risk gate
    -> PostgreSQL/SQLite checkpoint + reviewer decision
    -> versioned SolutionResponseV2
```

本地模型运行时的语义生成全部来自 llama-server；字符 n-gram 只作为可审计的 Compose 基线检索器和无模型测试 fixture。需求抽取按小字段组调用实时模型，使用紧凑 JSON 输出和主机侧 Pydantic/来源校验；model-facing brief 只保留身份字段，客户字段只以带原文引用的 facts 传输。单条事实的错误引用只降级为待核实，不会拖垮同一响应中的合法事实；抽取整体失败不会进入规则解析 fallback，而是返回 `model_unavailable` 或停在需求澄清门。发送给 llama.cpp 时对可约束的模型节点采用 `response_format=json_object` + 顶层 `json_schema` 的单一路径，避免同时发送两套 grammar 定义导致 sampler 初始化失败；响应仍由完整 Pydantic 契约二次校验。检索、草案或审核节点失败则返回 `model_unavailable`，不会使用固定模板伪造 v2 方案。Dify 适配器仍可用于对照实验，但不绕过 v2 API 的需求确认、安全硬门。

需求优先是方案生成的硬门：`needs_clarification` 和 `ready_for_confirmation` 状态不执行产品知识检索；Live API 在这两个需求阶段都可追加不可变客户输入并重新评估，但只有再次确认后的 `CustomerBriefV2` 才会进入方案图。字段事实、原文引用和冲突保留在同一 run 的 checkpoint 中，便于从澄清回合恢复而不重新创建 run。

## Local demo startup boundary

本机 Live API 的推荐入口是 `scripts/start_local_demo.py` 的单终端启动器。它先启动
llama-server 并轮询 `/v1/models` 确认目标 alias，再启动 Presales API 并等待 `/readyz` 返回 200，最后
启动 Gradio；三个子进程使用固定的本地端口和独立进程组，端口冲突、模型 alias 不一致或 readiness 失败均
在创建 run 前 fail fast。启动器收到 `SIGINT`/`SIGTERM` 时只清理自己创建的进程组，不终止已有服务或删除
checkpoint、模型和知识文件。离线 Replay 仅供 CI/契约校验使用，不是 Live 产品入口，也不会由 Gradio 启动。

## Risk boundaries

- 无证据不输出具体产品承诺
- 私有化、数据出域、合规和容量要求进入风险或待确认问题
- 个人演示机器的性能不外推为生产容量
- API Key 只在服务端环境变量中读取
- 文档中的提示词注入内容不拥有更高优先级
- Agent 不拥有任意代码执行、写库、发邮件和生产修改工具
- trace 只记录必要元数据，并在落盘前脱敏

## Compatibility strategy

核心包只保留当前 v2 数据模型和 HTTP 行为；历史结果作为不可被运行时读取的证据保存。正式运行时通过锁定的 runtime extra 安装：

- `uv sync --locked --extra runtime` 安装 FastAPI、LangGraph、LangGraph PostgreSQL checkpointer、psycopg 和 Uvicorn。
- SQLite 用于单机测试；Compose 使用项目 checkpoint 表、LangGraph 原生 PostgreSQL `PostgresSaver`、`tsvector` 和 pgvector schema。登记资料通过可选的 `presales-ingest` 一次性任务写入同一知识卷，API 在 SQL 层先做 tenant/ACL/revocation 过滤。
- Live API 依赖不可用时统一 fail closed；需求抽取和方案节点都不使用规则解析或固定模板代替模型输出。
- Dify 复用 v2 evidence/claim 契约时，需要经过同样的服务端校验。
- 有 CUDA：运行 QLoRA 和 llama.cpp/vLLM 真实实验；无 CUDA 时只报告 dry-run 和已运行的 CPU/Apple 结果。
