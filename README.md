# AI Presales Copilot

一个面向售前和解决方案架构师的可复现作品集项目：把客户需求、企业知识、方案架构、POC 验收、模型部署选型和风险审核串成一条可追溯的交付链路。

本项目解决的是“如何把 AI 能力变成可审核、可验收的售前方案”，不是面向一线工程师的终端问答产品。终端运维助手作为独立项目维护。

## 核心流程

```text
客户需求 → 需求结构化 → 证据检索 → 架构与 POC
        → RAG/Prompt/LoRA/部署策略 → 风险门 → 审核后的方案
```

## 可运行能力

- 无 API Key 的离线 RAG/方案基线、24 条黄金案例和结构化 schema 校验
- 显式状态 Agent：需求 → 检索 → 架构 → POC → 模型策略 → 风险门 → 输出
- SQLite checkpoint、人审 `approve/reject` 恢复、run/trace/thread 可观测记录
- Dify 工作流/API 适配、本地 Agent API 和可选 Gradio Demo
- RAG-first 的云 API、本地 llama.cpp/GGUF、轻量服务和 vLLM 部署决策
- 可复现的 QLoRA/LoRA 数据、评测、安全红队和部署基准入口

## 目录

```text
src/ai_presales_copilot/  售前 Agent、契约、检索、API、持久化和安全策略
data/knowledge/           合成产品、部署、安全和检索资料
data/evaluation/          客户需求黄金案例
data/finetuning/          版本化微调数据与 manifest
dify/                     Dify 工作流说明和响应契约
scripts/                  Demo、评测、Agent、训练和基准脚本
docs/                     架构、POC、部署、面试和安全材料
tests/                    不依赖外部服务的自动化测试
```

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

make test
make lint
make eval
make agent-eval
make security-check
```

运行离线方案 Demo：

```bash
PYTHONPATH=src python scripts/run_demo.py --case-id case-001
```

运行带人工审核的 Agent：

```bash
PYTHONPATH=src python scripts/run_agent.py \
  --case-id case-001 \
  --db .runtime/agent/demo.db \
  --trace .runtime/agent/case-001.jsonl

PYTHONPATH=src python scripts/run_agent.py \
  --case-id case-001 \
  --approve \
  --db .runtime/agent/demo.db
```

启动本地 API：

```bash
PYTHONPATH=src python scripts/serve_agent.py --port 8090
```

启动可选 Gradio 页面：

```bash
python -m pip install -e '.[demo]'
PYTHONPATH=src python demo/gradio_app.py --mode mock
```

## 设计边界

- 产品事实必须绑定知识库证据，不把模型记忆当作承诺。
- 缺少部署、容量、合规或产品证据时，输出风险和待确认问题。
- 高风险结论必须经过人工审核，Agent 不直接修改生产系统或外发消息。
- 合成案例和本机基准只用于工程演示，不代表客户生产准确率、SLA 或容量。
- 模型微调只承载稳定的格式、分类和决策行为，持续变化的事实由 RAG 提供。

详细材料：[`docs/architecture.md`](docs/architecture.md)、[`docs/agent-design.md`](docs/agent-design.md)、[`docs/api.md`](docs/api.md)、[`docs/interview.md`](docs/interview.md)。
