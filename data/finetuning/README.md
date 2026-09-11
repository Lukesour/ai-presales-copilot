# QLoRA 数据集与训练说明

本目录保存由 `scripts/build_finetune_dataset.py` 生成的合成对话数据。数据只用于作品集演示，不包含真实客户资料、价格、密钥或个人信息。

## 数据目标

微调目标是让小模型更稳定地完成以下行为：

- 提取行业、场景、部署、并发、时延和合规约束
- 输出售前方案的结构化 JSON
- 生成 POC 阶段、验收条件和澄清问题
- 对无证据、高风险、数据出域和容量承诺保持保守

产品事实、版本、价格、SLA、认证和实时知识仍通过 RAG 或人工审核提供，不通过微调把易变事实写死在权重里。

每条 user message 还包含结构化客户约束和同一轮检索得到的 `retrieved_evidence`；assistant target 是紧凑 JSON，并移除了运行时字段。这样评测的是“RAG context → 结构化方案生成”，不会要求 adapter 凭记忆猜测 held-out 案例的产品事实。

## 数据治理

- 使用 `messages` 对话格式，最后一条消息必须是 `assistant`
- train/dev/test 按客户案例划分，变体不会跨 split 泄漏
- `manifest.json` 记录生成器、数据统计和 SHA-256
- 提交前检查 PII、密钥、真实客户数据和上游许可证
- 训练与推理使用相同的 Qwen chat template
- conversational SFT 默认只对 assistant response 计算 loss，避免把用户问题当成监督目标
- 训练前执行 tokenizer length audit，避免 `max_length` 静默截断 JSON 尾部

生成和校验：

```bash
make build-finetune-dataset
make dataset-check
make finetune-token-audit
```

## 训练路径

Colab CUDA 推荐使用：

```bash
python -m pip install -e '.[finetune]'
python scripts/train_qlora.py --dry-run
python scripts/train_qlora.py
```

训练脚本会额外读取 `test.jsonl`，训练完成后写出 held-out test metrics；没有 CUDA 时 dry-run 会验证数据、配置和路径，但不会伪造训练结果。

也提供 LLaMA-Factory 配置：

```bash
llamafactory-cli train configs/finetune/llamafactory_qwen25_lora_sft.yaml
```

训练后必须在 `test.jsonl` 和独立安全集上比较 base 与 adapter，不以训练 loss 单独判断上线。adapter 和训练输出写入被 Git 忽略的 `.runtime/`，不提交大模型文件。
## Self-QA candidate filtering

Use the repository corpus by default so evidence references are checked against
real IDs. Add an ingested chunks manifest when evaluating versioned sources:

```bash
PYTHONPATH=src python scripts/build_self_qa.py \
  --input data/finetuning/train.jsonl \
  --chunks .runtime/knowledge/chunks.jsonl
```

Samples with unknown evidence IDs, invalid JSON/schema, PII, or instruction-like
content stay in the rejected layer. `--approved-id` is the only path that can
promote a filtered candidate to `expert_verified_gold`.
