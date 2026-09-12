# AI Presales Copilot

一个面向售前和解决方案架构师的可复现作品集项目：把客户需求、企业知识、方案架构、POC 验收、模型部署选型和风险审核串成一条可追溯的交付链路。

本项目解决的是“如何把 AI 能力变成可审核、可验收的售前方案”，不是面向一线工程师的终端问答产品。终端运维助手作为独立项目维护。

## 求职演示主线：需求优先

```text
客户原始需求 → intake → extract_requirements → assess_requirements
      → clarify / requirements_confirmation
      → query_rewrite → retrieve → draft → ground_claims
      → critic → repair(最多 1 次) → risk_gate → human_review → finalize
```

正式入口先接收客户原始文本或会议纪要，不接受已经填好的完整 Brief 作为新流程入口。系统展示字段状态、置信度、原文引用、缺失/冲突/警告；关键字段未补齐或未确认时，不会检索企业知识，也不会生成方案。项目只维护 `/v2` 公共 API；Dify 和 llama-server 的上游 `/v1` 协议属于外部边界。

第一阶段固定为 Docker Compose + 本地 Qwen3-8B GGUF（默认 Q4）+ llama-server + PostgreSQL/pgvector。模型权重不进 Git；方案节点没有可用模型或结构化输出非法时，结果是 `model_unavailable`，不会回退到固定模板伪造方案。需求抽取失败时只允许进入标记为 `deterministic_fallback` 的保守原文匹配路径，仍停在需求澄清/确认门，不会生成方案。

## 可运行能力

- Pydantic v2 严格 v2 契约、原始输入/轮次/字段事实溯源、证据 ID 绑定、来源版本/许可/ACL 字段
- 真实 LangGraph 编排、PostgreSQL 原生 `PostgresSaver` interrupt/resume、SQLite 测试回退、乐观锁和审核幂等
- FastAPI：认证、租户/项目上下文、RBAC、统一错误、request ID、events/feedback
- llama-server OpenAI-compatible 客户端、JSON Schema 请求和客户端二次校验
- 安全的本地/授权来源登记、HTML/PDF/DOCX/Markdown 分块、hash/locator/撤回接口
- Self-QA 候选过滤与 `raw_synthetic → filtered_synthetic → expert_verified_gold` 分层
- Dify 适配、本地 Agent API 和 Gradio（默认通过正式 API 调用）
- RAG-first 的云 API、本地 llama.cpp/GGUF、轻量服务和 vLLM 部署决策
- 可复现的 QLoRA/LoRA 数据、评测、安全红队和部署基准入口

## 目录

```text
src/ai_presales_copilot/  售前 Agent、契约、检索、API、持久化和安全策略
data/knowledge/           合成产品、部署、安全和检索资料
data/demo/                合成演示案例和需求优先脱敏 Replay 快照
data/evaluation/          客户需求黄金案例
data/finetuning/          版本化微调数据与 manifest
dify/                     Dify 工作流说明和响应契约
scripts/                  Demo、评测、训练、契约和基准脚本
docs/                     架构、POC、部署、面试和安全材料
tests/                    不依赖外部服务的自动化测试
```

## 快速开始

```bash
uv sync --locked --extra runtime --extra dev

PYTHONPATH=src:. uv run --locked --extra runtime --extra dev pytest -q
PYTHONPATH=src:. uv run --locked --extra runtime --extra dev ruff check src scripts tests demo/gradio_app.py
uv run python scripts/ingest_sources.py --chunks /tmp/chunks.jsonl --manifest /tmp/manifest.jsonl
```

PDF/DOCX 资料解析需要额外安装 `knowledge` extra：

```bash
uv sync --locked --extra runtime --extra dev --extra knowledge
```

运行正式 API Demo（需先启动上面的 Compose，并准备本地模型）：

```bash
uv run python scripts/run_demo.py --case-id demo-normal-001 --mode replay
```

启动 Phase 1 Compose（需要先准备模型文件）：

```bash
cp .env.example .env
mkdir -p models
# 用脚本下载并输出 hash（需要本机已安装 hf 或 huggingface-cli）
MODEL_DIR=models MODEL_FILE=Qwen3-8B-Q4_K_M.gguf ./scripts/download_model.sh
# 或将已校验的 Qwen3-8B GGUF Q4 文件放到 models/，文件名与 LLAMA_MODEL_FILE 一致
docker compose --env-file .env -f deploy/compose.agent.yaml up --build
curl -s http://127.0.0.1:8090/healthz
curl -s http://127.0.0.1:8090/readyz
```

也可以在本机运行 API，模型服务仍需先由 `llama-server` 在 `LLAMA_BASE_URL` 提供服务：

```bash
PRESALES_ALLOW_DEV_AUTH=true PRESALES_DEV_TOKEN=dev-token \
  uv run python scripts/serve_agent.py --allow-dev-auth --port 8090
```

创建一条需求优先 run：

```bash
curl -s http://127.0.0.1:8090/v2/projects/manufacturing/runs \
  -H 'Authorization: Bearer dev-token' \
  -H 'Idempotency-Key: demo-run-001' \
  -H 'X-Tenant-ID: local' -H 'X-User-ID: presales-demo' -H 'X-Roles: presales' \
  -H 'Content-Type: application/json' \
  -d '{"input":{"raw_request":"客户希望把维修手册和历史工单做成设备运维知识助手，回答必须可引用。","source":"meeting_notes"},"source":"meeting_notes"}'
```

响应先可能是 `needs_clarification` 或 `ready_for_confirmation`。补充信息使用
`POST /v2/runs/<run_id>/clarifications`，确认后使用
`POST /v2/runs/<run_id>/requirements/confirm`；澄清、确认、审核和反馈写接口都携带新的 `Idempotency-Key` 和响应中的 `state_version`。

高风险 run 会返回 `waiting_for_review`。审核必须使用 `reviewer`/`admin` 角色和新的幂等键：

```bash
curl -s http://127.0.0.1:8090/v2/runs/<run_id>/reviews \
  -H 'Authorization: Bearer dev-token' -H 'X-Roles: reviewer' \
  -H 'Idempotency-Key: demo-review-001' -H 'Content-Type: application/json' \
  -d '{"decision":"approve","reason":"已核对部署边界和引用","state_version":12}' # 替换为响应中的 state_version
```

启动 Gradio 页面（调用正式 API，不直接操作 Agent）：

```bash
uv sync --locked --extra demo
PRESALES_API_TOKEN=dev-token uv run python demo/gradio_app.py --mode api
```

Gradio 页面默认使用 `Demo Replay`，首屏先展示一条登记过的合成客户原始需求；页面不再提供场景下拉框或“辅助示例”按钮，避免把预填 Brief 误认为正式输入入口。切换到 `Live API` 后，页面加载、刷新和每次实时分析前都会检查 `/readyz`。
如果数据库、知识库或模型未就绪，会阻止创建 run，但不会影响 `Demo Replay`。

无模型或无 API 环境也可以直接运行求职演示：

```bash
PYTHONPATH=src python scripts/check_demo_replays.py
PRESALES_API_TOKEN=dev-token uv run python demo/gradio_app.py --mode api
```

Replay 仍保留正常、信息缺失后补充、高风险审核和冲突/注入阻断四条离线验收分支，但只通过仓库校验和环境变量选择，不作为首屏输入控件。需要查看其他登记分支时，可在启动前设置 `PRESALES_REPLAY_CASE=high_risk`。任意新文本必须切换到 `Live API`。
Replay 是静态快照，不访问 API、数据库或模型，也不代表生产模型效果。

重新从可用的正式 API 捕获快照（不会自动覆盖已有文件）：

```bash
PYTHONPATH=src python scripts/capture_demo_replays.py --api-url http://127.0.0.1:8090
```

实现细节和三分钟讲解顺序见 [`docs/demo-script.md`](docs/demo-script.md) 和
[`docs/demo-replay.md`](docs/demo-replay.md)。

来源导入和 Self-QA：

```bash
uv run python scripts/ingest_sources.py
uv run python scripts/build_self_qa.py --input data/finetuning/train.jsonl
```

撤回某个已登记资料版本（按 `source_id`，必要时再加 `content_hash`）：

```bash
PYTHONPATH=src uv run python scripts/revoke_source.py \
  --source-id repo-product-capability \
  --chunks .runtime/knowledge/chunks.jsonl \
  --manifest .runtime/knowledge/manifest.jsonl
```

Compose 环境请按 [`deploy/README.md`](deploy/README.md) 同时撤回 PostgreSQL 和知识卷。

## 设计边界

- 产品事实必须绑定知识库证据，不把模型记忆当作承诺。
- 缺少部署、容量、合规或产品证据时，输出风险和待确认问题。
- 高风险结论必须经过人工审核，Agent 不直接修改生产系统或外发消息。
- 对外演示入口是 `local-model` API 或当前 Replay。需求抽取的确定性 fallback 只负责保守识别原文事实，不是方案模板，也不能绕过确认门。
- 合成案例和本机基准只用于工程演示，不代表客户生产准确率、SLA 或容量。
- 模型微调只承载稳定的格式、分类和决策行为，持续变化的事实由 RAG 提供。

详细材料：[`docs/architecture.md`](docs/architecture.md)、[`docs/agent-design.md`](docs/agent-design.md)、[`docs/api.md`](docs/api.md)、[`docs/interview.md`](docs/interview.md)。
第一阶段逐项验收见 [`docs/phase1-acceptance.md`](docs/phase1-acceptance.md)；安全披露规则见 [`SECURITY.md`](SECURITY.md)。
