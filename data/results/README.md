# Measured Results

Only commit small JSON reports produced by the scripts. Do not commit model files, API keys, raw customer data or logs containing prompts.

Suggested labels:

- `offline-evaluation.json`: deterministic contract and safety baseline
- `q4-metal-c1.json`: Q4 model on native Apple Silicon with concurrency 1
- `q8-metal-c1.json`: Q8 model on native Apple Silicon with concurrency 1
- `q4-metal-c4.json`: Q4 model on native Apple Silicon with concurrency 4

`agent-evaluation.json` and any report whose `mode` refers to the retired offline
Agent are historical evidence only. Current evaluation writes `mode: v2-replay`
and must be generated from `data/demo/replays/` via `make eval`; no runtime path
may read a result report as input.

Current QLoRA evidence:

- `colab/qlora/compact-experiment-20260909.json`: Qwen2.5-0.5B-Instruct compact-contract adapter run on a Tesla T4. It contains a small, non-sensitive summary of the run; the adapter weights and full raw bundle remain in Google Drive.

Each report should be accompanied by the exact model file, llama.cpp commit, hardware, context length and launch flags in the README or experiment notes.
