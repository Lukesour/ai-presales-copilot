# Agent 容器化演示

这是第一阶段 Docker Compose 闭环：`presales-api`、`llama-server` 和 `PostgreSQL + pgvector`。API 使用本地开发 token；它没有替代企业 OIDC/JWT 网关、密钥管理或生产级身份平台。

从仓库根目录运行：

```bash
cp .env.example .env
# 把已校验的 Qwen3-8B GGUF Q4 文件放进 ./models/
docker compose -f deploy/compose.agent.yaml up --build
curl http://127.0.0.1:8090/healthz
curl http://127.0.0.1:8090/readyz
```

需要把登记的 Markdown/PDF/DOCX 资料导入 PostgreSQL 和 API 使用的只读知识卷时，执行一次：

```bash
docker compose --profile ingest -f deploy/compose.agent.yaml run --rm presales-ingest
docker compose -f deploy/compose.agent.yaml restart presales-api
```

`readyz` 只有在 PostgreSQL、知识索引、本地模型都可用时才返回 200。缺少模型或模型输出不符合 JSON Schema 时，业务 run 会显式返回 `model_unavailable`，不会伪造成功方案。

停止并保留 checkpoint：

```bash
docker compose -f deploy/compose.agent.yaml down
```

Compose 默认使用已解析的 llama.cpp immutable digest；升级时应显式更新并回归验证 `LLAMA_IMAGE`。模型文件通过只读 volume 注入，并用 `LLAMA_MODEL_SHA256` 写入 provenance。生产化还需要 TLS/OIDC、网络策略、资源限制、备份恢复、日志脱敏、镜像扫描、数据库迁移和高风险工具审批。
