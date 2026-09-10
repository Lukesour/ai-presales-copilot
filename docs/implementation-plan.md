# 2–3 周作品集实施计划

目标是在 `ai-presales-copilot` 上维护一个可公开、可复现、可面试演示的售前项目，而不是堆叠互不相关的 Demo。

## 第 1 周：需求、Agent 和应用闭环

### 目标

能用一个制造业设备运维案例，展示从客户输入到带证据方案的完整链路。

### 交付物

- `CustomerBrief`、`SolutionResponse` 和 JSON Schema 版本化契约。
- 显式 Agent 节点：需求、检索、架构、POC、模型策略、风险门、输出。
- PostgreSQL/SQLite checkpoint、run/trace/thread ID 和人工审核 approve/reject；Compose 路径使用 LangGraph 原生 `PostgresSaver` interrupt/resume。
- 无证据保守回答、提示词注入检测、敏感信息和无依据承诺检查。
- Dify 工作流说明、Gradio Agent 模式、本地 HTTP API。
- 24 条合成黄金问题集与离线评测。

### 验收

`case-001` 首次运行停在 `waiting_for_review`（`error_code=needs_review`）；人工 approve 后完成；没有证据时摘要包含“资料不足”，且不出现产品承诺。

## 第 2 周：POC、部署和微调实验链路

### 目标

让面试官看到你知道什么时候用 RAG、什么时候做微调，以及如何把模型策略与硬件/业务约束连接起来。

### 交付物

- 四阶段 POC：需求数据、RAG/Agent 基线、模型策略实验、验收生产建议。
- 云 API、llama.cpp、本地轻量服务、vLLM GPU 服务的决策矩阵。
- 72 条可追溯的合成对话数据，按源案例做 train/dev/test split。
- TRL + PEFT QLoRA 配置、LLaMA Factory 对照配置、dry-run 和 hash manifest。
- Colab QLoRA 运行手册和 base/adapter 对比协议。

### 验收

本机完成 dataset-check 和 finetune-dry-run，并在 Colab Tesla T4 上完成 compact QLoRA 实测；adapter 在 18 条 held-out synthetic cases 上达到 JSON parse `100%`、compact schema `14/18`、policy pass `18/18`。完整响应仍由 Agent/RAG 组装，不能把 compact schema 指标表述成生产业务准确率。

## 第 3 周：工程化、红队、文档和面试呈现

### 目标

把项目从“能运行”打磨成“能解释、能复现、能被审查”。

### 交付物

- Prompt injection、敏感数据、过度承诺和工具越权红队集。
- API 文档、架构图、容量/TCO 假设、上游许可证和个人实现边界。
- GitHub Actions：lint、unit test、offline eval、security check、dataset check。
- 3 分钟演示、简历 bullet、面试问答和一页项目 README。
- 只提交源代码、合成数据和结果摘要；不提交密钥、客户资料、模型权重和 runtime 数据卷。

### 验收

陌生人按 README 可在无 API Key 情况下完成测试、Agent 审核恢复、数据校验和 dry-run；所有性能数字均能追溯到原始报告。

## 日常工作节奏

1. 每天先跑 `make test lint eval agent-eval dataset-check`，避免文档和实验漂移。
2. 每个新增结论都写“证据/假设/验证动作”三者之一。
3. 每次模型、数据、prompt 或上游版本变化都更新 manifest/版本记录。
4. 每个演示失败路径都保留：无证据、合规、高风险、拒绝审核、API 不可用。

## 完成定义

项目完成不等于“训练出一个模型”，而是同时满足：

- 客户价值可讲清楚。
- Agent 状态、工具、审核和恢复可演示。
- POC 有退出标准和实测指标定义。
- 微调数据不泄漏、可复现、能比较 base/adapter。
- 安全边界、上游归属和未验证事项写清楚。
- CI 和本地命令能让第三方复现当前结论。
