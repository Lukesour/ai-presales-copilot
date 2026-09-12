# Contributing

先阅读 `AGENTS.md`，再按 `project_memory.md`、`任务进展.md`、对应功能页和任务页确认责任边界。
开发环境要求 Python 3.11/3.12 和 `uv`。不要提交模型权重、`.env`、客户资料、运行时数据库或未脱敏 trace。

```bash
uv sync --locked --extra runtime --extra dev --extra knowledge
make governance
make openapi-check
make schema-check
make test
make lint
make file-length
make demo-replay-check
make security-check SECURITY_OUTPUT=/tmp/security-evaluation.json
make eval EVAL_OUTPUT=/tmp/offline-evaluation.json
uv run python scripts/ingest_sources.py --chunks /tmp/chunks.jsonl --manifest /tmp/manifest.jsonl
docker compose --env-file .env.example -f deploy/compose.agent.yaml config
```

变更公共契约时先编辑 `contracts/openapi/src/`，再运行 `make openapi-check`；只有明确的生成操作才运行
`make openapi-build` 或 `uv run python scripts/export_schemas.py`。新增模型行为必须提供脱敏 Replay、失败路径和
可复现的模型/提示词/数据版本；模型生成数据只能进入 `filtered_synthetic`，不能自动晋升为 `expert_verified_gold`。

提交前确认 `git diff --check`、单元测试、权限/审核测试和文档中的命令均通过。涉及安全边界、数据库迁移、幂等、重试或兼容行为的代码应写清楚不变量和回滚方式；不得为了兼容退役项目 `/v1` 增加 alias、回退读取或双写。
