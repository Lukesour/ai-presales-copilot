# 演示与评测

## 责任域

`demo/`, `demo_controller.py`, `demo_replay.py`, `data/demo/`, `scripts/check_demo_replays.py`,
`evaluation.py` 和 `security/` 负责可复现演示与确定性证据。

## Replay 边界

Replay 是静态合成快照，不调用 API、模型、数据库或 `/readyz`，也不证明生产模型质量。
Live API 是真实本地模型运行的唯一入口。每份 Replay 必须标注捕获来源、模型/提示词版本和知识快照。

## 评测边界

评测分别覆盖契约、需求门、事实依据、安全、数据质量和模型性能。合成结果不得表述为客户准确率、SLA
或容量证据。

## 证据

- `docs/demo-replay.md`
- `docs/demo-script.md`
- `docs/evaluation.md`
- `docs/security-and-governance.md`
- `security/redteam-cases.jsonl`
