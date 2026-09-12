# Dify 售前助手复现

本目录保存 Dify 应用层的业务配置说明和输出契约，不包含 Dify 上游源码。

## 上游项目

- 仓库：[langgenius/dify](https://github.com/langgenius/dify)
- 建议使用 Dify 的稳定 release，而不是 `main`
- 首次启动时记录 release tag、commit、模型提供商和知识库版本
- Dify 的源代码、镜像和前端展示须遵守上游许可证；不要移除上游署名

## 启动方式

Dify 应用层不要放进 Colab：它需要数据库、向量库、插件守护进程和持久化文件存储；Colab 只负责一次性的 llama.cpp 性能实验。当前本机已按官方 Docker Compose 配置准备运行时文件到被忽略的 `.runtime/dify/docker/`，端口使用 8081：

```bash
cd /Users/suan/Desktop/求职/解决方案/ai-presales-copilot
COMPOSE_PROFILES=weaviate,postgresql,collaboration \
docker compose -p ai-presales-dify \
  -f .runtime/dify/docker/docker-compose.yaml \
  --env-file .runtime/dify/docker/.env up -d
```

首次访问 `http://localhost:8081/install` 完成初始化。重启或查看状态：

```bash
docker compose -p ai-presales-dify \
  -f .runtime/dify/docker/docker-compose.yaml \
  --env-file .runtime/dify/docker/.env ps
```

如果你在另一台机器重新部署，仍使用 Dify 官方 release/compose 文件，并重新记录版本、镜像 digest、模型提供商和知识库版本；不要把 `.runtime/` 或 Dify 的数据卷提交到 GitHub。

## 知识库资料

将仓库根目录 `data/knowledge/*.md` 上传到一个名为 `ai-presales-catalog` 的 Dify 知识库。建议按文档类型分别上传，并保留文件名与版本号。

推荐配置：

- 小段落优先，标题和列表不拆散
- 打开检索测试，检查是否能召回部署、安全和推理资料
- 为无召回结果设置固定回复：资料不足，请补充客户约束或产品资料
- 不在系统提示词中写死价格、SLA、认证或准确率
- 开启结构化输出能力时，正式 v2 契约使用 `output_schema_v2.json`；`draft_schema_v2.json` 是 llama-server 模型输出契约。两者都是派生产物，由 `scripts/export_schemas.py` 生成，并通过 `make schema-check` 检查漂移，禁止手工修改。

## 工作流节点

当前可录屏的最小闭环是：

`开始 → 知识检索 → LLM → 最终方案回复`

完整作品集闭环建议按下面的显式节点搭建，并与本仓库的离线 Agent 保持同一份输出契约：

`开始 → 需求结构化 → 知识检索 → 证据校验 → 方案架构 → POC 计划 → 模型策略 → 风险/人工审核 → 结构化输出`

其中风险/人工审核节点是关键的售前能力展示：高风险、合规约束、注入迹象或无证据时，输出 v2 `review.status=pending`，把方案交给 API reviewer 确认，而不是让模型自行越权继续执行。

LLM 节点的关键配置是：

- `context.enabled=true`
- 上下文变量选择 `知识检索.result`
- 知识库只绑定 `企业 AI 解决方案售前知识库`
- `top_k=4`，经济型关键词检索，关闭重排模型依赖
- Phase 1 使用 Qwen3-8B GGUF Q4；0.5B 仅用于 smoke test，`temperature=0.0`，结构化节点由服务端限制 `max_tokens=4096`

这条 Dify 链路用于对照“需求进入、证据检索、模型生成、结果展示”；正式本地模型闭环应使用 Compose API，因为它负责鉴权、ACL、checkpoint、证据绑定和审核。0.5B 只适合 smoke test，不应被包装成生产级方案生成模型。

如果要扩展到完整售前流程，再按以下顺序增加节点：

1. `需求结构化`：提取行业、场景、数据类型、部署、并发、时延和合规
2. `证据与风险检查`：没有来源的事实改成待确认项
3. `条件分支`：高风险或低置信度进入追问，否则输出方案
4. `结构化响应`：返回与 `output_schema_v2.json` 对齐的 JSON

本仓库正式提供 FastAPI v2 本地 Agent/API：

```bash
PRESALES_ALLOW_DEV_AUTH=true uv run python scripts/serve_agent.py --allow-dev-auth --port 8090
curl http://127.0.0.1:8090/healthz
```

它使用 LangGraph + SQLite/PostgreSQL checkpoint，提供当前 `/v2/projects/{project_id}/runs`、`/v2/runs/{run_id}/events`、`/v2/runs/{run_id}/reviews` 等接口。项目不提供自有 `/v1` HTTP 兼容层；Dify 的 `/v1/chat-messages` 只属于外部 Dify API 边界。

Dify App API 的密钥只能由 `DifyClient` 在服务端调用，不能放进 Gradio 前端代码或浏览器请求中。
