# 技术选型与 GitHub 上游研究

## 选型结论

| 能力 | 选型 | 为什么适合售前作品集 | 本仓库边界 |
|---|---|---|---|
| 应用工作流 | [Dify](https://github.com/langgenius/dify) | 可视化知识库、Workflow、模型提供商和 API，适合录屏展示客户交付 | 使用配置、资料、提示词和 API 适配，不声称开发 Dify 内核 |
| Agent 编排 | [LangGraph](https://github.com/langchain-ai/langgraph) + PostgreSQL `PostgresSaver` + 依赖无关测试 fallback | 显式 state graph、节点边界持久化、interrupt 审核恢复和 durable execution，适合展示可控 Agent | Compose 正式路径直接执行 `StateGraph` + 原生 `PostgresSaver`；SQLite/fallback 只服务单机测试和历史 fixture |
| 训练 | [TRL](https://github.com/huggingface/trl) + [PEFT](https://github.com/huggingface/peft) | 直接支持 conversational SFT、assistant-only/completion-only loss 和 LoRA | 只提交数据治理、配置、脚本和评测协议 |
| 训练对照 | [LLaMA Factory](https://github.com/hiyouga/LlamaFactory) | 命令行、LoRA/QLoRA、多种训练/导出/推理路径，便于面试展示工具熟悉度 | 只保留 YAML、dataset mapping 和 runbook |
| GPU serving | [vLLM](https://github.com/vllm-project/vllm) | OpenAI-compatible server、批处理和 LoRA adapter 服务，适合生产候选路径 | 只定义选型和验证输入，不在本机伪造 GPU 结果 |
| Edge/local serving | [llama.cpp](https://github.com/ggml-org/llama.cpp) | GGUF、CPU/Metal/CUDA、本地 OpenAI-compatible 服务，适合数据不能出域 POC | 启动、客户端、压测、指标和选型分析由本项目维护 |
| 安全评测 | [Promptfoo](https://github.com/promptfoo/promptfoo) | 可扩展 red-team plugins、OWASP framework 和本地评测 | 固定安全用例另用标准库检查，Promptfoo 作为可选增强 |
| 可观测性 | 本地 JSONL；生产候选 Phoenix/OpenTelemetry | 无外部服务也能检查 trace，生产可接 OTEL/LLM tracing | 当前 trace 只做演示，不等于生产 telemetry 平台 |

## 为什么不是“一个万能 Agent”

售前交付中，需求结构化、资料检索、容量输入、风险判断和最终输出的责任边界不同。把所有事情交给一个自由循环的 Agent 会让结果难以回归、难以审核，也很难向客户解释。这里采用固定节点 + 有限工具 + 风险门，模型只在受控位置承担文本生成。

## 为什么是 RAG-first

产品能力、版本、价格和安全条款会变化，且需要引用。把这些事实写进权重会增加更新和审计成本；因此先把事实放入带来源/版本/权限的知识库。LoRA/QLoRA 只用于稳定行为、格式、分类和工具参数，并在 held-out 与对抗集上验证是否真的带来收益。

## 为什么两条训练路径

TRL + PEFT 更便于在 Python 中写可审计、可测试的训练脚本；LLaMA Factory 更适合快速复现实验、导出和 OpenAI-style 推理接口。两者共享数据 manifest 和评测集，避免“工具不同就无法比较”。

## 许可证和公开仓库检查

公开前逐项记录：上游 commit/release、模型 revision、模型许可证、训练数据授权、依赖许可证、容器基础镜像和结果生成日期。Dify 的发行许可包含其额外条件，模型和训练框架也可能有独立许可证；不要把“GitHub 可见”理解成“所有内容可任意商用”。

## 当前没有声称的能力

- 没有 CUDA 的机器不会报告 QLoRA loss、显存或 adapter 质量提升。
- 没有真实客户数据不会报告生产准确率、SLA、ROI 或合规通过。
- 没有认证/合同证据不会输出“已认证”或法律结论。
- 没有真实目标硬件压测不会给出容量采购数字。
