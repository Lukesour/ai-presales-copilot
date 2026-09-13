# Project Memory

本文件只保存当前仍会影响后续工作的项目决策、未解决问题和下一步；不记录历史流水、
不替代任务详情，也不授权生产操作或外部写入。

## Active Decisions

- **2026-09-11 — 当前项目公共入口是需求优先 `/v2`。** 新 run 只接收客户原始输入，需求未澄清或确认前不得检索或生成方案。项目自有旧 `/v1`、完整 Brief 入口和规则 Agent 不再作为兼容面；Dify 与 llama-server 的上游 `/v1` 仅属于外部协议边界。
- **2026-09-11 — 公共 HTTP 契约采用 OpenAPI-first。** 手写来源位于 `contracts/openapi/src/`，`dist/` 与 Dify/model schema 均为生成或校验产物；Pydantic 负责运行时验证，不成为公共 HTTP 契约的第二个权威。
- **2026-09-11 — 事实结论必须可追溯。** 方案中的事实 claim 必须绑定 evidence ID、来源版本和定位；无证据时输出风险或澄清问题，不用模板伪造产品承诺。
- **2026-09-13 — 本机演示只保留 Live API。** Gradio 不暴露 Replay 模式；需求抽取和方案节点都依赖实时模型。离线 Replay 仅作为 CI/契约快照保留，模型/schema/来源失败时 fail closed，不使用规则解析替代客户事实。
- **2026-09-11 — 项目治理采用渐进式 300 行 ratchet。** 新文件以单一责任和 300 行为目标，既有超长文件首期只报告，不通过无关重构掩盖当前工作区变更。
- **2026-09-11 — 文档与代码说明使用双语分工。** 治理、任务和产品文档使用中文；源代码注释、Docstring 和公共 API 描述默认使用英文。

## Open Issues

- **FILE-RATCHET-001 — 当前存在多个超过 300 行的既有源文件。** Owner: repository maintainer. Evidence: `make file-length`. Close incrementally by responsibility-based splits; the initial rollout remains report-only.
- **RUNTIME-001 — 共享部署仍需真实 OIDC/JWT、生产观测、模型供应链和容量证据。** Owner: deployment/security owner. Evidence: `docs/security-and-governance.md`, `docs/phase1-acceptance.md`. Close only with dated, redacted, authorized evidence;本次治理不执行这些外部操作。

## Next Steps

- Future cross-module work must use a new active task page and be archived under
  `docs/tasks/archive/<year>/` after completion.
- Keep `功能列表.md` conservative: do not promote a capability to `Available` from source presence alone; require matching contract, registration, runtime and evidence.
- Regenerate active evaluation and fine-tuning inputs after the clean-break schema is accepted; keep historical result reports isolated from runtime readers.
- Split oversized workflow and contract files only when a second reason to change is demonstrated and protecting tests are identified.
- Before any real deployment or external integration, create a separate sensitive task with authorization, preflight, rollback and sanitized evidence.
