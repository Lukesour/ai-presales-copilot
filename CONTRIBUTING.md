# Contributing

开发环境要求 Python 3.11/3.12 和 `uv`。不要提交模型权重、`.env`、客户资料、运行时数据库或未脱敏 trace。

```bash
uv sync --locked --extra runtime --extra dev --extra knowledge
uv run pytest -q
uv run ruff check src scripts tests migrations
uv run python scripts/ingest_sources.py --chunks /tmp/chunks.jsonl --manifest /tmp/manifest.jsonl
docker compose --env-file .env.example -f deploy/compose.agent.yaml config
```

变更契约时同时运行 `uv run python scripts/export_schemas.py`，检查 `dify/*_schema_v2.json` 是否同步。新增模型行为必须提供脱敏 fixture、失败路径和可复现的模型/提示词/数据版本；模型生成数据只能进入 `filtered_synthetic`，不能自动晋升为 `expert_verified_gold`。

提交前确认 `git diff --check`、单元测试、权限/审核测试和文档中的命令均通过。涉及安全边界、数据库迁移、幂等、重试或兼容行为的代码应写清楚不变量和回滚方式。
