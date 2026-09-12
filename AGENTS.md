# Agent Operating Contract

本仓库是 AI 售前与解决方案作品集项目的单仓开发权威。它包含需求优先
Agent、证据检索、方案输出、POC、模型实验、演示和验证材料。它不是客户生产
系统，也不授权部署、外部写入、发送消息或处理真实客户数据。

## Sources Of Truth

- `docs/architecture.md` owns durable runtime architecture, ownership and data flow.
- `contracts/openapi/src/` owns hand-written public HTTP contracts; `dist/` is generated.
- `功能列表.md` indexes approved capabilities and their delivery coverage.
- `任务进展.md` indexes active work; task details live under `docs/tasks/`.
- `project_memory.md` contains only active decisions, open issues and next steps.
- `docs/engineering/` owns naming, comments, Python, testing, contract and data/model rules.
- `docs/security-and-governance.md` owns security, privacy, red-team and external-operation boundaries.
- `dify/*.json` and exported model schemas are derived artifacts unless a document explicitly says otherwise.

Implementation, tests, fixtures, experiment manifests and result reports provide evidence;
they do not silently override the authorities above.

## Startup Reading Order

Before a non-trivial change, read:

1. `AGENTS.md`.
2. `project_memory.md` and the relevant entry in `任务进展.md`.
3. The affected feature page under `docs/features/` and `docs/architecture.md`.
4. The affected OpenAPI source, Pydantic models, fixtures, tests and scripts.
5. `docs/engineering/` and `docs/security-and-governance.md` when the change touches their boundary.

If two authorities conflict, stop and record the conflict in the task page. Do not resolve
it by duplicating a rule into a less authoritative document.

## Repository Boundary

- This is the current single-repository authority for the portfolio project.
- New public behavior is requirements-first `/v2`; project-owned `/v1` compatibility is not maintained.
- External protocols such as Dify `/v1/chat-messages` and llama-server `/v1/chat/completions`
  are upstream boundaries, not project-owned compatibility routes.
- Do not commit model weights, `.env` files, credentials, real customer material, runtime databases,
  raw private traces or external service data.
- Do not encode local absolute paths in contracts, CI, generated artifacts or reproducible commands.
- Historical reports may remain as evidence, but active scripts must not read them as runtime input.

## Priority And Risk

Resolve conflicts in this order:

1. Correctness
2. Security and privacy
3. Reliability and data integrity
4. Contract and release safety
5. Architecture
6. Maintainability
7. Documentation
8. Developer experience

Classify the change before editing:

- **Local**: one owner module, no public contract, persistence, auth, security or external-system effect.
- **Boundary**: API, OpenAPI, persistence, migration, demo contract, data pipeline or cross-module behavior.
- **Sensitive**: secrets, user data, auth, permissions, privacy, deployment, production or destructive operations.

The classification selects verification; it does not authorize external operations.

## Workflow

1. Analyze owner, current behavior, evidence and compatibility boundary.
2. Plan one scoped outcome and record acceptance evidence in the task page.
3. Implement the smallest complete change while preserving unrelated worktree changes.
4. Verify focused tests, then the applicable governance, contract and security gates.
5. Review diffs for stale status, duplicate authority, secret exposure, broken links and scope drift.
6. Update only the authority whose durable truth changed; archive completed task pages.

Never claim completion when a required check was skipped. Report the exact command, reason and residual risk.

## Responsibility Model

L0-L3 describe responsibility height inside a feature owner. They are not folders or identifier prefixes.

- **L0 Policy / Value**: pure values, deterministic rules and narrow stable contracts.
- **L1 Building Block**: one replaceable codec, validator, client, store, parser or adapter mechanism.
- **L2 Workflow**: one requirements, retrieval, solution, review, evaluation or demo flow.
- **L3 Boundary**: API routes, composition, startup, scheduling and handoff between workflows.

Dependencies point downward inside an owner. L3 must not inspect another owner's private payload or bypass
its validation boundary. Public wire contracts are separate from persistence records and UI/session state.

## File And Documentation Ratchet

- One hand-written file has one primary responsibility and one primary reason to change.
- Do not split into `Part1`, `Chunk2`, `New`, `Old`, `Legacy`, `Utils` or `Misc` files.
- New hand-written source, test, migration, script and task/detail files target 300 physical lines or fewer.
- Existing oversized files are report-only during the initial rollout; future blocking mode requires an explicit
  governance decision and a responsibility-based split.
- `功能列表.md` and `任务进展.md` remain at or below 150 lines.
- Feature, task and engineering pages remain at or below 300 lines and 40 KB.
- Generated, vendored, lock, binary, notebook and runtime files are excluded from the line ratchet.

## Contracts And Clean-break Policy

- New or changed public HTTP behavior is OpenAPI-first.
- `contracts/openapi/src/` is hand-edited; `contracts/openapi/dist/` is generated and never hand-edited.
- Pydantic models enforce runtime behavior and are checked against the public contract.
- Dify and model-facing JSON Schema files are derived artifacts and must pass drift checks.
- Project-owned `/v1` routes, old complete-Brief adapters, old rule Agent paths and old fixture schemas are removed,
  not extended with aliases or fallback readers.
- An incompatible persisted checkpoint fails closed with an actionable reset/migration message; it is never silently
  converted or deleted.
- Applied database migrations are immutable. New migrations receive a unique version and a concrete outcome.

## Comments, Naming And Data

Follow these authorities:

- `docs/engineering/naming.md` for modules, types, functions, routes, schemas, fixtures and documents.
- `docs/engineering/comments.md` for comments, Docstrings, TODOs, security notes and compatibility explanations.
- `docs/engineering/python.md` for Python structure, typing, I/O and error boundaries.
- `docs/engineering/testing.md` for deterministic fixtures, model fakes and verification layers.
- `docs/engineering/contracts.md` for OpenAPI, Pydantic, Dify and generated-schema ownership.
- `docs/engineering/data-and-models.md` for dataset, prompt, model, provenance and experiment rules.

Governance documents use Chinese. Source comments and public API descriptions default to English.
All model, prompt, dataset and replay changes must retain source, version, hash, license and sensitivity metadata.

## Verification Commands

Run the narrowest applicable checks:

- `make governance`
- `make openapi-check`
- `make file-length`
- `make test`
- `make lint`
- `make security-check`
- `make demo-replay-check`
- `git diff --check`

Boundary or sensitive changes also require the affected API, persistence, security and demo tests. These commands
must not deploy, SSH, mutate production, send messages or access user-owned external data.
