# 简历项目素材库｜AI 售前与解决方案方向

这份文档故意保留“长版本”，适合先建立完整素材库，再根据简历版面、岗位 JD 和面试官关注点删减。当前 clean-break 基线是 4 条 Replay、12 条微调对话和 63 个通过的 Python 测试；文中 24/72/18 等数字均明确标为历史实验，不应当作当前默认评测事实。模型质量数字必须注明是合成 held-out 集、compact contract 还是完整业务响应。

## 0. 项目基本信息

| 项目项 | 建议填写内容 |
| --- | --- |
| 项目名称 | 企业 AI 解决方案售前实验室（Manufacturing Presales AI Solution Lab） |
| 项目角色 | 独立完成需求抽象、方案设计、Agent/POC 开发、模型策略、评测与交付文档 |
| 项目性质 | 面向制造业设备运维的端到端 AI 解决方案作品集；以售前演示和概念验证为目标 |
| 项目周期 | `[20XX.XX–20XX.XX]`，按实际情况填写 |
| 项目链接 | `[GitHub 仓库链接]`，建议提供 README、架构图、Demo、评测结果和运行说明 |
| 目标岗位 | AI 售前、解决方案顾问、售前技术支持、AI 解决方案工程师、交付/POC 工程师 |
| 核心业务场景 | 设备运维知识问答、故障初筛、维修建议生成、方案与部署选型辅助 |
| 项目边界 | 重点证明“能把业务问题转成可验证的 AI 方案”；不把实验室 Demo 表述成生产系统或客户正式上线项目 |

## 1. 项目定位

### 一句话定位

面向制造业设备运维场景，构建一个从客户需求澄清、知识检索、解决方案生成、POC 设计、模型策略选择到风险审核和部署评测的 AI 售前实验室，用一个可运行项目展示需求分析、技术架构、POC 管理、模型选型、工程实现和客户沟通能力。

### 面试官应当看到的能力

- 能够从“客户想要一个智能助手”继续追问业务目标、数据来源、用户、部署环境、并发、时延、合规和验收标准。
- 能够将需求拆成业务流程、系统架构、模型策略、POC 范围和可量化的 Exit Criteria，而不是只展示一个聊天页面。
- 能够理解 RAG、Agent、提示词、LoRA/QLoRA、量化、云 API、本地推理、vLLM 和 llama.cpp 的适用边界。
- 能够把 Demo 变成可复现、可评测、可审计、可交接的交付物，并对幻觉、越权、敏感信息和不受控工具调用负责。

## 2. 推荐直接放入简历的长版本

### 企业 AI 解决方案售前实验室｜Agent / RAG / POC / QLoRA

**项目角色：独立完成方案设计、开发、评测与交付文档｜项目周期：`[20XX.XX–20XX.XX]`**

**技术栈：** Python、Pydantic v2、FastAPI、LangGraph、RAG、结构化输出、PostgreSQL/pgvector、SQLite、Docker Compose、GitHub Actions、TRL/PEFT、QLoRA、LLaMA Factory、GGUF、llama.cpp、vLLM、OpenAI-compatible API、Promptfoo

- **需求分析与售前方案：** 围绕制造业设备运维场景，将行业、业务、数据、部署、峰值并发、时延、成本和合规约束结构化，形成需求澄清表、解决方案 Brief、架构说明、部署决策、TCO/容量估算和演示脚本，将“做一个 AI 助手”转化为可评审、可验证的交付方案。

- **需求优先 Agent 工作流：** 先接收客户原始需求，再用 `intake → extract_requirements → assess_requirements → clarify / requirements_confirmation` 判断缺口，确认后才进入 `query_rewrite → retrieve → draft → ground_claims → critic → repair → risk_gate → human_review → finalize`；以 PostgreSQL/SQLite checkpoint、幂等键、state version、暂停恢复、trace_id/run_id 和失败状态覆盖从客户原话到方案交付的完整闭环。

- **RAG 与结构化交付：** 基于 Dify/Gradio 复现售前应用交付链路，定义 JSON Schema、证据引用、无证据保守回答、假设条件、风险项、POC 计划和模型策略等输出字段，并提供 OpenAI-compatible API，使同一套方案既能演示，也能被前端或其他系统集成。

- **POC 设计与验收：** 将概念验证拆分为数据与基线、知识库/RAG、Agent 工作流、业务验收四个阶段，为每个阶段定义目标、活动、交付物和 Exit Criteria；围绕回答正确性、证据可追溯性、需求覆盖率、结构化输出、风险拦截和性能指标组织验收，而不是只以“能聊天”作为 POC 成功标准。

- **可量化评测：** 维护 4 条覆盖正常、需求补充、高风险审核和冲突/注入阻断的注册 Replay；当前离线评测 schema 和需求门均为 `4/4`，高风险审核分支为 `1/1`，并通过安全与证据绑定校验。

- **模型策略与部署选型：** 建立“RAG/提示词优先，只有在稳定任务模式和高质量标注数据足够时再考虑 LoRA/QLoRA”的决策逻辑；为云 API、本地 GGUF/llama.cpp、vLLM 和量化部署定义适用场景、约束与回滚路径，并明确 TTFT、p95、吞吐、CPU RSS、GPU VRAM、结构化输出通过率和成本等基准指标，避免在没有实测数据时虚构 SLA 或吞吐承诺。

- **微调数据与 QLoRA 链路：** 从 4 条注册 Replay 生成 12 条当前 ShareGPT-style 合成对话，按场景进行 `train/dev/test = 6/3/3` 隔离，生成 SHA-256 manifest、LLaMA Factory 配置、TRL/PEFT QLoRA 训练脚本和 Colab runbook；历史 Tesla T4 compact 实验另行保留并标注为历史证据。

- **安全与治理：** 针对中文、英文和间接提示注入、越权承诺、过度代理、无限资源消耗、隐私信息和无依据回答设计 12 条 red-team cases，安全评测 `12/12` 通过；对输入、输出和敏感信息执行策略检查，对高风险、合规、证据不足和提示注入情形进入人工审核，并以 JSONL trace 记录可审计过程。

- **工程化与交付：** 提供模块化 Python 包、单元测试、Replay 评测、安全检查、数据集检查、Docker Compose 部署、健康检查/就绪检查、API 文档、架构图、技术选型、面试问答和演示脚本；当前验证结果为 `63 passed`、Ruff 检查通过、锁文件校验通过、依赖安全扫描无已知漏洞、Docker Compose 配置通过。

## 3. 详细项目说明素材

### 3.1 业务背景

制造企业通常拥有设备说明书、维修手册、故障码表、巡检记录、服务工单和专家经验，但这些资料分散在 PDF、表格、知识库或个人经验中。传统关键词检索难以结合上下文，通用大模型又可能在证据不足时编造维修结论；因此客户真正需要的不是一个“会聊天的模型”，而是一套能够理解运维需求、引用内部资料、输出结构化建议、保留人工判断边界并可在不同部署环境运行的解决方案。

### 3.2 解决的问题

- 需求不清：客户目标、用户角色、数据范围、部署位置和验收方式经常没有被同时说明。
- 知识不可追溯：回答没有引用资料，售前无法解释“为什么这样建议”。
- POC 无验收：Demo 可以展示，但没有数据集、通过标准、失败案例和上线门槛。
- 模型选型凭感觉：没有把质量、时延、并发、成本、数据安全和运维能力放在同一张决策表中。
- 风险难控制：提示注入、敏感信息、越权操作、无依据承诺和无限工具调用可能导致客户不可接受的结果。

### 3.3 端到端业务流程

`客户需求输入 → 需求澄清 → 知识检索 → 证据校验 → 解决方案架构 → POC 计划 → 模型/部署策略 → 风险审核 → 结构化交付`

### 3.4 个人承担的工作

| 售前环节 | 我的工作 | 对应交付物 |
| --- | --- | --- |
| 需求挖掘 | 抽象业务目标、用户、数据、环境、并发、时延、合规和验收条件 | 需求 schema、澄清问题、假设清单 |
| 方案设计 | 设计 RAG、Agent、工具边界、审核门、状态持久化和部署形态 | 架构图、技术选型、部署决策 |
| POC 规划 | 按阶段拆解范围、输入、活动、交付物和退出标准 | POC plan、Exit Criteria、演示脚本 |
| 模型决策 | 比较 RAG、Prompt、LoRA/QLoRA、量化、本地和云端部署 | 模型策略、容量估算、基准方案 |
| 数据准备 | 设计数据格式、案例隔离、统计和哈希校验 | ShareGPT JSONL、manifest、dataset_info |
| 工程实现 | 编写 Agent、工具、API、checkpoint、日志、脚本和测试 | Python 包、CLI、Docker、CI |
| 风险治理 | 设计策略检查、red-team cases、脱敏和人工审核流程 | 安全规则、审计 trace、风险文档 |
| 客户交付 | 将技术结果翻译成客户能评审的材料和演示路径 | Solution Brief、README、FAQ、Demo Script |

## 4. 技术实现细节

### Agent 与状态管理

- 采用显式节点和显式状态，避免让单个大模型自由规划所有事情。
- `intake` 负责需求结构化、假设和澄清问题；`retrieve` 负责知识检索与证据校验；`architect` 输出方案架构；`poc` 输出验证计划；`model_strategy` 输出模型和部署建议；`risk_gate` 决定自动交付或人工审核；`finalize` 生成最终响应。
- 工具调用采用有限集合和输入边界，工具返回结构化结果；不允许 Agent 任意执行 shell、网络写操作或不可审计的外部动作。
- 每个 run 具有 `run_id`、`trace_id` 和 `thread_id`；checkpoint 保存状态，支持人工审核后恢复，拒绝则终止并记录原因。
- 核心流程保持轻量、可测试；正式 v2 运行时直接使用 LangGraph StateGraph，节点边界写入 SQLite/PostgreSQL checkpoint，人工审核通过 API 事务恢复并进入 finalize；退役实现只保留为历史报告证据。

### RAG 与证据策略

- 先判断需求是否需要外部证据，再从知识库检索候选内容。
- 证据经过校验后才绑定到回答；证据不足时返回限制、假设和待补充资料，不生成无依据的确定性承诺。
- 证据字段与方案字段分离，便于评测“有回答”和“有依据”两个维度。
- Dify 用于低代码工作流和售前展示，Python Agent 用于可测试的核心逻辑；两者通过结构化合同对齐。

### 模型与部署策略

| 方案 | 适用情况 | 主要风险/代价 | POC 中的定位 |
| --- | --- | --- | --- |
| RAG + Prompt | 知识经常变化、需要引用内部资料、样本较少 | 检索质量决定上限，需维护知识库 | 默认基线 |
| LoRA/QLoRA | 输出格式、术语、分类或稳定任务模式需要固化，且有高质量样本 | 数据质量、过拟合、评测和训练成本 | 训练链路与决策条件 |
| 云端 API | 需要快速验证、已有合规可接受的云服务 | 数据出域、成本、供应商依赖 | 快速 POC |
| 本地 GGUF + llama.cpp | 边缘/内网、低资源、隐私要求较高 | 速度、上下文和模型能力受限 | 本地部署候选 |
| vLLM | GPU 服务、较高并发、需要统一服务接口 | GPU、运维和资源成本 | 服务化候选 |

### 评测指标

- 质量：需求字段覆盖率、结构化 schema 通过率、证据有效率、无证据保守率、人工偏好或业务准确率。
- Agent：节点完成率、工具参数有效率、状态恢复成功率、审核门正确率、失败可解释性。
- 性能：TTFT、端到端延迟、p50/p95、吞吐、峰值并发、CPU RSS、GPU VRAM。
- 工程：测试通过率、可重复运行、数据集 hash、日志脱敏、API 健康检查和容器启动成功率。
- 业务：人工处理时长、首次解决率、专家介入率、知识复用率、试点用户满意度和单位请求成本。

## 5. 当前验证结果与历史实验口径

| 结果 | 当前事实 | 推荐表述 |
| --- | --- | --- |
| 当前 Replay | 4 条注册场景；schema `4/4`；需求门 `4/4`；高风险审核 `1/1` | “维护 4 条需求优先 Replay，覆盖确认门、证据绑定和人工审核分支。” |
| 安全回归 | 12 条 red-team cases，`12/12` 通过 | “覆盖注入、隐私、越权、无限消耗和无依据回答，安全回归 12/12 通过。” |
| 当前数据集 | 12 条合成对话；train/dev/test 为 6/3/3；按 Replay 场景隔离；manifest/hash 有效 | “完成可追溯、按场景隔离的数据集构建和校验。” |
| 工程验证 | `63 passed`；Ruff、锁文件和依赖安全扫描通过；Docker Compose config 通过 | “建立测试、静态检查、依赖审计和容器配置验证。” |
| 历史 QLoRA | Colab Tesla T4 compact profile：JSON parse `18/18`、schema `14/18`、policy `18/18`；完整响应仍由 Agent/RAG 组装 | “完成历史可复现 QLoRA 训练与 held-out 对比，并明确 compact contract 与完整业务响应的边界。” |

## 6. 不同简历长度版本

### 6.1 一页简历推荐版（6 条）

**企业 AI 解决方案售前实验室｜独立项目｜`[时间]`**

- 面向制造业设备运维场景，负责从需求澄清、知识检索、方案架构、POC 验收、模型选型到风险审核的端到端 AI 解决方案设计。
- 设计 `intake → extract_requirements → assess_requirements → clarify/requirements_confirmation → query_rewrite → retrieve → draft → ground_claims → critic/repair → risk_gate → human_review → finalize` 需求优先 Agent，接入字段级溯源、PostgreSQL/SQLite checkpoint、人工审核恢复、脱敏 trace 和 OpenAI-compatible API。
- 基于 Dify/Gradio 搭建演示链路，将 POC 拆分为数据基线、RAG、Agent、业务验收四阶段，定义每阶段交付物和 Exit Criteria。
- 维护 4 条 Replay 场景，当前 schema 与需求门校验均为 `4/4`，并覆盖高风险人工审核与冲突/注入阻断分支。
- 生成按 Replay 场景隔离的 12 条 ShareGPT-style 数据（train/dev/test=`6/3/3`），实现 TRL/PEFT QLoRA、LLaMA Factory 配置、manifest/hash、数据检查和评估脚本；历史 Tesla T4 compact 实验单独保留。
- 设计 RAG-first 的模型决策矩阵，比较云 API、本地 GGUF/llama.cpp、vLLM 和 QLoRA；覆盖注入、隐私、越权和无限消耗的 12 条安全回归全部通过，并以 Docker/CI/文档完成交付。

### 6.2 三条精简版（适合项目空间很小的简历）

**企业 AI 解决方案售前实验室｜Python / Agent / RAG / Dify / POC / QLoRA**

- 面向制造业设备运维，独立完成需求结构化、方案架构、POC 四阶段验收和云端/本地/量化部署选型，形成可演示、可评测、可审计的解决方案闭环。
- 设计需求优先 Agent、证据检索与安全硬门、PostgreSQL/SQLite checkpoint、人工审核恢复和 OpenAI-compatible API；当前 4 条 Replay 覆盖关键需求门、证据和审核分支。
- 构建当前 12 条按 Replay 场景隔离的数据并完成 TRL/PEFT QLoRA 与 LLaMA Factory 训练链路；历史 Tesla T4 compact decision contract 对比和 18 条 held-out 指标作为单独历史证据披露；12 条安全 red-team cases `12/12` 通过。

### 6.3 一句话版

独立构建制造业设备运维 AI 售前实验室，打通需求澄清、RAG/Agent、POC 验收、模型策略、QLoRA 数据链路、安全审核和可部署 API，并用 4 条 Replay 场景和 12 条安全案例完成回归验证。

### 6.4 偏售前/客户方案岗位版本

- 将制造业运维需求拆解为业务目标、数据边界、部署约束、并发/时延和验收标准，输出解决方案 Brief、架构、POC 计划、风险清单和演示脚本。
- 通过 RAG-first 决策和云 API/本地部署/量化/微调对比，向客户解释“为什么选这个方案、什么时候需要微调、如何验收、如何控制风险”。
- 以 4 条 Replay 场景、4 阶段 POC Exit Criteria 和 12 条 red-team cases 建立从 Demo 到可验证方案的证据链。

### 6.5 偏售前技术/解决方案工程师版本

- 使用 Python 实现显式 LangGraph 状态图 Agent、结构化 schema、PostgreSQL/SQLite checkpoint、人工审核事务暂停/恢复、JSONL trace 和 OpenAI-compatible API。
- 基于 TRL/PEFT 实现 QLoRA 训练入口，完成 ShareGPT 数据构建、源案例隔离、hash manifest、assistant/completion-only loss 兼容和 held-out 评估脚本。
- 通过 pytest、Ruff、Replay eval、安全 eval、Docker Compose 和 CI 将 Demo 纳入可复现交付流程。

## 7. 与校招售前/解决方案岗位的能力映射

| 岗位能力 | 项目证据 | 面试表达重点 |
| --- | --- | --- |
| 客户需求挖掘 | 需求 schema、澄清问题、假设、业务/数据/环境约束 | 先理解业务结果，再决定模型和产品形态 |
| 解决方案设计 | RAG、Agent、工具边界、审核门、部署矩阵 | 能解释架构中每个组件为什么存在 |
| POC 管理 | 四阶段计划、交付物、Exit Criteria、失败案例 | 能控制范围、预期和验收，避免 POC 变成无限试错 |
| AI 技术理解 | RAG、Prompt、LoRA/QLoRA、量化、GGUF、vLLM | 能说明技术选项的适用边界和代价 |
| 客户价值意识 | TCO/容量估算、成本/延迟/质量指标、业务 KPI | 不只谈模型参数，而是谈可落地的效果和成本 |
| 风险与合规 | 注入、隐私、越权、无证据、人工审核、脱敏 trace | 对模型不确定性有边界意识 |
| 工程交付能力 | API、Docker、CI、测试、文档、runbook | 方案能运行、能验证、能交接 |
| 沟通与呈现 | Solution Brief、架构图、演示脚本、面试 FAQ | 能让业务、技术和管理者听懂同一套方案 |

## 8. 面试讲述稿

### 30 秒版本

这是我为 AI 售前/解决方案岗位做的端到端作品集。场景是制造业设备运维，我没有只做一个聊天 Demo，而是把客户需求澄清、RAG 检索、Agent 方案生成、POC 验收、模型/部署选型和风险审核串成一个可运行流程。项目包含 Dify 演示、Python/LangGraph Agent、QLoRA 数据和训练链路、Docker Compose/API 以及评测体系；当前 4 条 Replay 分支和 12 条安全案例通过校验，历史 Tesla T4 compact QLoRA 实验另行披露。

### 90 秒版本

我选择制造业设备运维，是因为它同时体现知识问答、结构化输出、证据追溯和私有化部署需求。首先接收客户原话，再把业务目标、用户、资料来源、部署/出域边界、峰值并发、时延和验收标准结构化；缺关键字段时先追问，未确认时不检索、不生成方案。确认后用显式 Agent 完成查询改写、检索、方案生成、证据绑定、批评修订和风险门。RAG 作为默认基线，因为维修资料会变化且必须引用证据；只有在输出格式或稳定任务模式需要固化、并且有足够高质量数据时，才进入 LoRA/QLoRA。POC 被拆成四阶段，每阶段都有交付物和退出条件。为了证明方案不是“看起来能跑”，当前 Replay 覆盖正常、补充、高风险和冲突/注入四条分支，安全集覆盖 12 条案例。最后，我提供了 OpenAI-compatible API、Docker Compose、checkpoint、审计 trace 和文档，使方案具备演示、评测和交接条件。

### 三分钟展开顺序

1. 先讲客户问题和业务价值：资料分散、专家经验难复用、回答需要有依据、部署环境可能受限。
2. 再讲需求澄清：用户是谁、要解决什么 KPI、有哪些数据、是否允许出域、峰值并发和验收标准是什么。
3. 展示方案架构：Dify/Gradio 负责演示，Python Agent 负责显式流程，RAG 提供证据，审核门控制高风险输出，API/Docker 负责集成和交付。
4. 解释技术决策：为什么先 RAG，什么条件下微调，云 API、本地 GGUF/llama.cpp 和 vLLM 如何选择。
5. 展示验证结果：4 条 Replay 场景、12 条安全回归、63 个 Python 测试、12 条隔离数据集，以及标注为历史证据的 T4 QLoRA compact held-out 对比。
6. 主动说明边界：这是个人作品集/POC，不是客户生产上线；QLoRA 指标来自 18 条合成 held-out cases，compact schema 不是完整业务准确率，生产仍需更大黄金集、结构化解码和人工审核。

## 9. 高频面试问题与建议回答

### Q1：为什么要做 Agent，而不是一个 RAG 问答？

RAG 解决“从资料中找依据”，但售前交付还要完成需求澄清、架构设计、POC 规划、模型选型和风险审核。我的 Agent 将这些步骤拆成显式节点，便于观察、评测、暂停和人工接管；如果场景只需要知识问答，则会优先交付更简单的 RAG，而不会为了使用 Agent 而增加复杂度。

### Q2：为什么不一开始就微调？

微调改变的是模型行为，不能替代实时知识库、权限和证据链。制造业维修资料可能持续变化，所以先用 RAG 建基线；当问题集中在固定输出格式、术语风格、分类或稳定流程，并且有足够高质量标注数据时，再用 LoRA/QLoRA 评估增益。是否微调要由 held-out 评测、成本、延迟和维护代价共同决定。

### Q3：你的微调真的训练完成了吗？

完成过一次历史可复现的 Colab Tesla T4 实验。实验使用 24 个合成源案例、train/dev/test=`42/12/18` 的历史数据，采用 compact decision contract，让 0.5B 模型只生成摘要、建议、风险、澄清问题、证据 ID 和审核状态；在同一 18 条 held-out split 上，adapter JSON parse 为 `18/18`、compact schema 为 `14/18`、policy pass 为 `18/18`。我不会把这些数字包装成真实业务准确率，也不会把历史数据当作当前默认输入；完整 POC、模型策略和证据对象仍由 Agent/RAG 确定性组装。

### Q4：如何控制大模型幻觉？

通过四层控制：需求和输出 schema 限制表达范围；检索和证据校验要求关键结论绑定资料；无证据时输出限制、假设和待补资料，而不是编造；高风险、合规或疑似注入场景进入人工审核。评测中把“有回答”和“有有效证据/正确保守”拆开统计。

### Q5：POC 怎么判断成功？

不能只看 Demo 是否可用。我会先锁定业务案例和非目标范围，再定义数据基线、RAG、Agent 和业务验收四个阶段；每阶段明确输入、交付物、指标和 Exit Criteria，例如 schema 通过、证据可追溯、需求覆盖、风险拦截、p95 和成本。未达到门槛时，优先缩小范围或补充数据，而不是直接承诺生产上线。

### Q6：什么时候选本地部署，什么时候选云 API？

先看数据是否允许出域和客户的运维能力，再看质量、时延、并发、成本、模型可控性和升级方式。云 API 适合快速验证；本地 GGUF/llama.cpp 适合内网、边缘和低资源场景；GPU 并发服务可考虑 vLLM；若需要稳定行为或固定格式，再评估 LoRA/QLoRA。最终会用同一套黄金案例和性能基准比较，而不是凭模型名做决定。

### Q7：项目中的 Agent 是否可以直接用于生产？

不能直接这样承诺。当前项目证明了流程设计、可测试性、审核、日志脱敏、API 和容器化基础；生产化还需要接入真实知识库和权限系统、真实业务数据脱敏、身份认证、限流、密钥管理、监控告警、灾备、人工运营流程和更大规模性能压测。

### Q8：你的个人贡献是什么？

我负责从业务场景和需求模型开始，完成方案架构、Agent 状态和工具边界、Dify/Gradio 演示、POC 验收、模型与部署决策、微调数据和训练链路、安全规则、测试评测、Docker/API 和文档。Dify、llama.cpp、LangGraph、TRL/PEFT 等基础能力来自上游开源项目，我的贡献是围绕售前场景完成业务抽象、适配、编排、验证和交付。

## 10. 简历措辞边界

| 可使用的真实口径 | 不建议直接使用的口径 | 原因 |
| --- | --- | --- |
| “在 Colab T4 完成 compact QLoRA 训练与 held-out 对比” | “完成大模型微调并提升准确率 30%” | 当前数据为合成案例，compact schema 不是业务准确率 |
| “定义并实现性能基准指标” | “系统稳定支持 1000 并发” | 尚未完成对应规模实测 |
| “基于 Dify 搭建/适配演示工作流” | “自主开发 Dify 平台” | Dify 是上游开源平台 |
| “基于 llama.cpp 完成本地部署适配和 benchmark 入口” | “自研推理引擎” | 推理引擎能力来自上游项目 |
| “当前 Replay 分支校验通过；历史评测报告回归 24/24” | “线上准确率 100%” | 当前和历史结果都是离线合成案例，不是线上真实业务 |
| “设计人工审核门和拒绝/恢复流程” | “系统完全消除幻觉和安全风险” | AI 系统只能降低风险，不能绝对消除 |
| “构建当前 12 条合成数据并按 Replay 场景隔离” | “拥有真实客户数据” | 数据为合成数据，不能冒充客户数据 |

## 11. 投递前个性化清单

- 将项目周期、GitHub URL、个人姓名、项目是否独立完成、是否有公开 Demo 替换为真实信息。
- 如果岗位偏售前，把“需求澄清、价值、POC、验收、客户沟通、方案文档”放在技术名词之前。
- 如果岗位偏解决方案工程，把 Agent 状态、工具边界、API、Docker、CI、评测和故障处理放前面。
- 如果 JD 提到私有化部署，把本地 GGUF/llama.cpp、vLLM、数据不出域、资源估算和回滚策略展开。
- 如果 JD 提到模型训练，把 QLoRA 数据治理、case-level split、manifest、T4 实测、held-out 评估和 compact/full contract 边界展开。
- 只保留自己能在 1–3 分钟内解释清楚的技术名词；技术栈过长时优先保留 `Agent、RAG、Dify、POC、QLoRA、Python、Docker、评测`。
- 简历中所有百分比、并发、延迟、成本和效果提升都必须能指向评测脚本、结果文件或实测记录。
- 面试前准备一次从需求输入到最终方案的完整 Demo，并准备无证据、高风险和人工审核三个失败分支。

## 12. 英文简历版本

### Enterprise AI Presales Solution Lab | Agent, RAG, POC & QLoRA

**Role:** Independent project owner, responsible for solution design, implementation, evaluation and delivery documentation.

- Designed an end-to-end AI presales workflow for manufacturing equipment maintenance, covering requirement clarification, evidence-grounded RAG, solution architecture, four-phase POC acceptance, model strategy and deployment selection.
- Implemented a requirements-first LangGraph stateful Agent with PostgreSQL/SQLite checkpointing, field-level source quotes, bounded clarification, requirements confirmation, evidence binding, human approval/rejection and resume, redacted JSONL traces and an OpenAI-compatible API; the current Replay contract covers four validated branches.
- Built 12 case-isolated ShareGPT-style samples (`train/dev/test = 6/3/3`) from the current Replay corpus, with TRL/PEFT QLoRA and LLaMA Factory training configurations, dataset manifests and validation scripts; a historical Colab Tesla T4 compact experiment is reported separately from the current baseline.
- Defined a RAG-first model decision matrix across cloud APIs, local GGUF/llama.cpp, vLLM and parameter-efficient fine-tuning; 12/12 red-team security cases passed for prompt injection, privacy, excessive agency, unbounded consumption and unsupported claims.

## 13. 项目事实披露

面试中建议主动说明：这是面向求职展示的个人端到端 POC/作品集，不是客户生产上线项目。Dify、llama.cpp、LangGraph、TRL/PEFT、LLaMA Factory、vLLM 和 Promptfoo 的基础能力来自上游开源项目；个人工作集中在制造业售前场景抽象、需求与输出契约、Agent 编排、工具边界、POC 验收、模型/部署决策、数据治理、评测、安全规则、适配器、部署脚本和结果分析。当前已验证的是合成案例、规则、T4 QLoRA compact contract 和工程链路；真实业务数据效果、生产级容量和客户 KPI 均不应写成已完成事实。
