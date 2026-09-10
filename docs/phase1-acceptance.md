# Phase 1 验收清单

目标是第三方在干净环境中用 Docker Compose 启动三个核心服务（API、llama-server、PostgreSQL/pgvector；迁移和导入为一次性辅助服务），导入登记资料，调用真实本地模型完成一条售前 run，并能在审核点恢复。

## 主路径

1. `cp .env.example .env`，准备与 `LLAMA_MODEL_FILE` 同名的 Qwen3-8B GGUF Q4 文件，并填写 `LLAMA_MODEL_SHA256`。
2. `docker compose --env-file .env -f deploy/compose.agent.yaml up --build`。
3. `GET /healthz` 返回 200；`GET /readyz` 只有 PostgreSQL、知识索引和 llama-server 全部正常才返回 200。
4. 可选执行 `docker compose --profile ingest -f deploy/compose.agent.yaml run --rm presales-ingest`，资料通过登记的来源进入 PostgreSQL/pgvector 和只读知识卷。
5. 用 `POST /v1/projects/{project_id}/runs` 创建 run；重复相同幂等键返回同一 `run_id`，替换 brief 则返回 409。
6. 读取 run/events；高风险、合规、无证据或注入案例必须为 `waiting_for_review`，并保存 reviewer、角色、理由、时间、state_version 和幂等键。
7. `approve` 后通过 LangGraph 原生 `Command(resume=...)` 进入 `finalize` 并变为 `complete`，`reject` 后状态为 `rejected`；重复审核不生成新结果，另一幂等键不能覆盖历史决定。

## 失败门

- llama-server 不可用：状态为 `model_unavailable`，没有伪造的固定模板方案。
- 模型返回非法 JSON/不符合 schema：最多一次结构化重试，仍失败则 `model_unavailable`。
- 模型引用未知 `evidence_id`：引用被丢弃，claim 标记 `needs_review`，并触发审核风险。
- 未授权 tenant/project/role：检索前拒绝，不能通过生成后删除文本来“隔离”。
- 远程资料未在来源登记、非 HTTPS、robots 不允许或解析发现敏感内容：导入失败并保留原因。

## 当前边界

第一阶段的 pgvector 表、SQL `tsvector` 检索和 LangGraph PostgreSQL checkpoint 已接入；没有配置 embedding worker 时，向量列为空，仍可用 PostgreSQL 全文检索。模型、GPU、吞吐和准确率必须以实际硬件、权重 hash、llama.cpp digest、数据集和日期为单位单独报告。
