# 需求优先评测数据

`replay_cases.jsonl` 是当前 v2 Replay 的评测索引，不是生产输入，也不包含真实客户资料。
数据来源、版本、hash、许可、敏感级别和用途由同目录的 `manifest.json` 统一记录。

更新场景或 Replay 后，必须重新计算 manifest 并运行：

```bash
make demo-replay-check
```

历史评测报告不得作为运行时输入；当前运行时只读取已登记的 `data/demo/scenarios.json` 和
`data/demo/replays/`。
