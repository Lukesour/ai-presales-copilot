# AI Presales Copilot

一个面向售前和解决方案架构师的可复现作品集项目：把客户需求、企业知识、方案架构、POC 验收、模型部署选型和风险审核串成一条可追溯的交付链路。

本项目解决的是“如何把 AI 能力变成可审核、可验收的售前方案”，不是面向一线工程师的终端问答产品。终端运维助手作为独立项目维护。

## 第一阶段运行闭环

```text
intake → clarify → query_rewrite → retrieve → draft → ground_claims
      → critic → repair(最多 1 次) → risk_gate → human_review → finalize
```

第一阶段固定为 Docker Compose + 本地 Qwen3-8B GGUF（默认 Q4）+ llama-server + PostgreSQL/pgvector。模型权重不进 Git；没有可用模型或结构化输出非法时，结果是 `model_unavailable`，不会回退到固定模板伪造方案。

## 可运行能力

- Pydantic v2 严格 v2 契约、证据 ID 绑定、来源版本/许可/ACL 字段
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
data/demo/                三个合成演示案例和脱敏 Replay 快照
data/evaluation/          客户需求黄金案例
data/finetuning/          版本化微调数据与 manifest
dify/                     Dify 工作流说明和响应契约
scripts/                  Demo、评测、Agent、训练和基准脚本
docs/                     架构、POC、部署、面试和安全材料
tests/                    不依赖外部服务的自动化测试
```

## 快速开始

```bash
uv sync --locked --extra runtime --extra dev

uv run pytest -q
uv run ruff check src scripts tests
uv run python scripts/ingest_sources.py --chunks /tmp/chunks.jsonl --manifest /tmp/manifest.jsonl
```

PDF/DOCX 资料解析需要额外安装 `knowledge` extra：

```bash
uv sync --locked --extra runtime --extra dev --extra knowledge
```

运行正式 API Demo（需先启动上面的 Compose，并准备本地模型）：

```bash
uv run python scripts/run_demo.py --case-id case-001 --mode api --review approve
```

离线规则引擎只用于回归检查，必须显式标记为 fixture：

```bash
uv run python scripts/run_demo.py --case-id case-001 --mode fixture
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

创建一条结构化 run：

```bash
curl -s http://127.0.0.1:8090/v1/projects/manufacturing/runs \
  -H 'Authorization: Bearer dev-token' \
  -H 'Idempotency-Key: demo-run-001' \
  -H 'X-Tenant-ID: local' -H 'X-User-ID: presales-demo' -H 'X-Roles: presales' \
  -H 'Content-Type: application/json' \
  -d '{"brief":{"schema_version":"2.0","case_id":"manufacturing-001","industry":"制造业","use_case":"设备运维知识助手","data_types":["维修手册 PDF","历史工单"],"deployment":"私有化","capacity":{"peak_concurrency":5,"full_answer_target_ms":10000},"governance":{"egress_allowed":false,"audit_required":true},"raw_request":"请给出可引用、可审计的设备故障问答 POC。"}}'
```

高风险 run 会返回 `waiting_for_review`。审核必须使用 `reviewer`/`admin` 角色和新的幂等键：

```bash
curl -s http://127.0.0.1:8090/v1/runs/<run_id>/reviews \
  -H 'Authorization: Bearer dev-token' -H 'X-Roles: reviewer' \
  -H 'Idempotency-Key: demo-review-001' -H 'Content-Type: application/json' \
  -d '{"decision":"approve","reason":"已核对部署边界和引用"}'
```

启动 Gradio 页面（调用正式 API，不直接操作 Agent）：

```bash
uv sync --locked --extra demo
PRESALES_API_TOKEN=dev-token uv run python demo/gradio_app.py --mode api
```

Gradio 页面默认使用 `Live API`。页面加载、刷新和每次实时生成前都会检查 `/readyz`；
如果数据库、知识库或模型未就绪，会阻止创建 run，但不会影响 `Demo Replay`。

无模型或无 API 环境也可以直接运行求职演示：

```bash
PYTHONPATH=src python scripts/check_demo_replays.py
PRESALES_API_TOKEN=dev-token uv run python demo/gradio_app.py --mode api
```

页面切换到 `Demo Replay` 后，可展示正常、信息缺失和高风险审核三个合成案例。
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
- `mock`/旧规则 Agent 只保留为测试 fixture；对外演示入口是 `local-model` API。
- 合成案例和本机基准只用于工程演示，不代表客户生产准确率、SLA 或容量。
- 模型微调只承载稳定的格式、分类和决策行为，持续变化的事实由 RAG 提供。

详细材料：[`docs/architecture.md`](docs/architecture.md)、[`docs/agent-design.md`](docs/agent-design.md)、[`docs/api.md`](docs/api.md)、[`docs/interview.md`](docs/interview.md)。
第一阶段逐项验收见 [`docs/phase1-acceptance.md`](docs/phase1-acceptance.md)；安全披露规则见 [`SECURITY.md`](SECURITY.md)。
