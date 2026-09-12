# Colab QLoRA 运行手册

本手册用于一次性的 GPU 实验，不把 Colab 当成生产环境。Colab 的 GPU 型号、可用时间和免费资源配额会动态变化；每次实验都必须保存 GPU、驱动、包版本、模型 revision、数据 manifest、配置、checkpoint 和评估结果。详见 [Google Colab 官方 FAQ](https://research.google.com/colaboratory/faq.html)。

## 1. 你必须先完成的事情

| 任务 | 是否必须 | 说明 |
| --- | --- | --- |
| 准备 Google 账号并打开 Colab | 是 | 进入 [Google Colab](https://colab.research.google.com/) |
| 把当前仓库推到 GitHub | 强烈建议 | notebook 会通过 HTTPS clone；建议公开仓库，不要把密钥写进仓库 |
| 选择 GPU runtime | 是 | Colab 菜单：Runtime → Change runtime type → Hardware accelerator → GPU |
| 授权 Google Drive | 推荐 | notebook 默认开启，用于保存 checkpoint、adapter 和报告；不想授权可改 `USE_DRIVE=False`，但必须在结束前下载 zip |
| 点击并运行 notebook 单元格 | 是 | 我不能代替你登录 Google、接受 Colab 资源分配或授权 Drive |

当前项目仓库为 `https://github.com/Lukesour/ai-presales-lab.git`，需要先在本地提交并推送代码，GitHub 上的 `main` 才会成为可复现的来源。不要把 Hugging Face Token、GitHub Token、客户文档或个人隐私写进 URL、代码和 notebook 输出。

## 2. 推荐路径：始终从 GitHub canonical source 打开最新版 notebook

仓库已经提供 [`notebooks/qlora_colab.ipynb`](../notebooks/qlora_colab.ipynb)。本项目的固定入口是：

[直接在 Colab 打开 GitHub main 上的最新版 QLoRA notebook](https://colab.research.google.com/github/Lukesour/ai-presales-lab/blob/main/notebooks/qlora_colab.ipynb)

每次开始新实验都使用上面的链接。它会从 `Lukesour/ai-presales-lab` 的 `main` 分支加载文件；不要从 Colab 的 Recent、Google Drive 副本或浏览器旧 tab 继续运行。Colab 官方说明 notebook 可以从 GitHub 加载，但 Drive/Colab 中的副本可能是另一份独立文件。[Google Colab FAQ](https://research.google.com/colaboratory/faq.html)

如果使用 Colab 菜单打开：

1. 打开 Colab。
2. 选择 File → Open notebook → GitHub。
3. 输入 `Lukesour/ai-presales-lab`，选择分支 `main`。
4. 选择 `notebooks/qlora_colab.ipynb`。
5. 第一个配置单元格已经绑定 canonical repository；通常只需要确认：

   ```python
   PROJECT_REPO_URL = "https://github.com/Lukesour/ai-presales-lab.git"
   PROJECT_BRANCH = "main"
   USE_DRIVE = True
   LOW_MEMORY = False
   ```

6. 先选择 GPU runtime，再依次运行所有单元格，不要跳过 GPU preflight、数据检查和 dry-run。

notebook 会打印 `repo`、`branch` 和 `commit`。正式训练前确认它们分别是：

```text
repo: https://github.com/Lukesour/ai-presales-lab.git
branch: main
commit: 当前 GitHub main 的最新 commit
```

如果 notebook 报“已有错误项目目录”，说明当前 runtime 中 `/content` 残留了旧 clone。选择 Runtime → Disconnect and delete runtime，再通过上面的固定链接重新打开并连接；不要手动把旧目录改名后继续训练。

notebook 已经负责：安装 `finetune-colab` extra、保留 Colab 自带 PyTorch/CUDA、检查 GPU、重建当前 12 条合成数据、保存 `pip-freeze` 和 runtime 元数据、把训练输出直接写入 Drive、训练后比较 base/adapter、打包结果。历史 T4 报告使用的 24/72 数据规模仅作为历史证据保留。

## 3. 手动路径（notebook 无法打开时）

### 3.1 先选择 GPU，再检查 runtime 是否正确

在 Colab 菜单中选择 GPU runtime，然后执行。`nvidia-smi` 只是辅助展示命令；某些运行时可能没有将它放入 PATH，训练预检以 `torch.cuda.is_available()` 和 PyTorch 设备信息为准：

```python
!nvidia-smi
```

```python
import torch
assert torch.cuda.is_available(), "没有 CUDA GPU，请重新选择 GPU runtime"
print(torch.__version__)
print(torch.cuda.get_device_name(0))
print(round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2), "GB")
print("bf16:", torch.cuda.is_bf16_supported())
```

如果 `!nvidia-smi` 报 `command not found`，执行下面的 PyTorch 检查：

```python
import torch
assert torch.cuda.is_available(), "当前不是 GPU runtime，请重新选择 GPU 并连接"
print(torch.cuda.get_device_name(0))
print(round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2), "GB")
```

只要 PyTorch 能看到 CUDA，`nvidia-smi` 缺失本身不会阻止训练；如果 PyTorch 也看不到 CUDA，则需要重新选择 GPU runtime。

免费 runtime 的 GPU 不保证固定型号；本项目默认的 Qwen2.5-0.5B 4-bit QLoRA 适合先做小规模可复现实验。不要因为分配到了更大 GPU 就直接把结果写成通用性能或生产 SLA。

### 3.2 拉取代码并安装依赖

```python
!git clone https://github.com/<your-user>/ai-presales-lab.git /content/ai-presales-lab
%cd /content/ai-presales-lab
!python -m pip install -q -e .
!python -m pip install -q -e '.[finetune-colab]'
```

`finetune-colab` 不声明 `torch`，避免不必要地覆盖 Colab 自带的 CUDA 版 PyTorch；它也不声明 `torchao`，因为本实验采用 `bitsandbytes + NF4` 的 QLoRA 路线。Colab 基础镜像若预装了旧版 `torchao`，notebook 安装单元会将这个未使用的可选后端移除，避免 PEFT 的 TorchAO dispatcher 因环境版本不兼容而阻塞普通 LoRA adapter 加载。训练依赖包括 Transformers、TRL、PEFT、bitsandbytes、datasets 和 accelerate。QLoRA 的 4-bit NF4 配置与训练逻辑见 [Hugging Face bitsandbytes 文档](https://huggingface.co/docs/transformers/quantization/bitsandbytes) 和 [TRL SFTTrainer 文档](https://huggingface.co/docs/trl/sft_trainer)。

### 3.3 构建数据、校验数据、dry-run

```python
!PYTHONPATH=src python scripts/build_finetune_dataset.py
!PYTHONPATH=src python scripts/check_finetune_dataset.py
!PYTHONPATH=src python scripts/audit_finetune_tokens.py \
  --model Qwen/Qwen2.5-0.5B-Instruct \
  --max-length 5120 \
  --strict \
  --output data/results/colab/qlora/token-audit.json
!PYTHONPATH=src python scripts/train_qlora.py --dry-run
```

预期结果：当前 train/dev/test 为 `6/3/3`，总计 12 条；ID 唯一；assistant target 全部是合法 JSON；manifest 中的 SHA-256 校验通过；dry-run 输出 `dataset and training configuration parsed successfully`。随后 token audit 会报告各 split 的 p50/p90/max 和是否超过 `max_length`。如果数据检查或 token audit 失败，不要继续启动正式训练。

### 3.4 正式训练

默认配置：

- 基座：`Qwen/Qwen2.5-0.5B-Instruct`。
- 量化：4-bit NF4 + double quantization。
- Tesla T4 默认固定使用 `float16`；不要仅依据 `torch.cuda.is_bf16_supported()` 的探测结果在 T4 上启用 BF16。
- Trainer 默认关闭 AMP，使用 FP32 adapter 参数和无 GradScaler 训练；量化线性层仍使用 FP16 compute。这是为 T4/当前 PyTorch 组合设置的兼容性选项，不代表全量模型使用 FP32。
- LoRA：`r=16`、`alpha=32`、`dropout=0.05`，覆盖 Q/K/V/O、上下投影和 gate 投影。
- 训练：5 epochs、learning rate `5e-5`、batch size 1、gradient accumulation 8（有效 batch size 8）、gradient checkpointing、`paged_adamw_8bit`；按 dev loss 选择最优 checkpoint。
- 序列长度：默认 5120；小显存时使用 4096。训练前必须查看 token audit；配置在发现 overflow 时会直接停止，避免把结构化 JSON 的结尾截掉。
- 评估和保存：按 epoch 执行，最多保留 2 个 checkpoint。

运行：

```python
!PYTHONPATH=src python scripts/train_qlora.py \
  --config configs/finetune/trl_qlora.json
```

预配置 notebook 会先运行一次 `--smoke-test`：只执行一个 optimizer step，验证量化模型、LoRA 参数、dtype、Accelerate 和 bitsandbytes 的组合，再启动完整训练。训练命令的 stdout/stderr 会保存到 `data/results/colab/qlora/qlora-smoke-test.log` 和 `qlora-training.log`；失败时还会复制到 Drive 的 `failed-runs/`，避免只看到 `CalledProcessError`。

训练完成后，脚本会创建一个只用于 held-out test 的 evaluation-only `SFTTrainer`。它先使用与 train/dev 相同的 tokenizer、chat template、最大长度和 completion-only loss 规则，把原始 `prompt`/`completion` 转成 `input_ids`、`labels` 等模型输入，再执行 test loss 评估。不要把 `remove_unused_columns=False` 当作修复：它只能阻止列被删除，不能把原始文本 tokenization 成模型输入。

如果显存不足，使用低显存配置：

```python
!PYTHONPATH=src python scripts/train_qlora.py \
  --config configs/finetune/trl_qlora_colab_lowmem.json
```

低显存配置保持 batch size 1、gradient accumulation 8、最大长度 4096；如果 token audit 仍提示溢出，应先缩短证据上下文或使用更大显存，而不是把截断结果当成有效质量实验。

### 3.5 中断后续跑

如果训练中断，先把 checkpoint 复制到持久化位置，然后查看目录：

```python
from pathlib import Path
print(sorted(Path('/content/drive/MyDrive/ai-presales-lab-results/active-training').glob('checkpoint-*')))
```

选择最新的 `checkpoint-*` 目录，重新启动 runtime、重新运行安装和数据检查，然后执行：

```python
!PYTHONPATH=src python scripts/train_qlora.py \
  --config /content/trl_qlora_runtime.json \
  --resume-from-checkpoint /content/drive/MyDrive/ai-presales-lab-results/active-training/checkpoint-XXX
```

预配置 notebook 默认将训练输出写入 `/content` 本地磁盘，训练结束后再复制到 Drive，减少 Drive 挂载文件系统对 Trainer 的影响；如需跨 runtime 恢复，可将 `TRAIN_OUTPUT_ON_DRIVE=True`，续跑前仍需要你确认 checkpoint 路径，不能盲目使用旧 checkpoint。

## 4. 训练后必须做的对比评估

base 和 adapter 必须使用同一个 `data/finetuning/test.jsonl`、相同生成参数和相同评测脚本。示例：

```python
!PYTHONPATH=src python scripts/evaluate_finetuned_model.py \
  --split data/finetuning/test.jsonl \
  --max-new-tokens 4096 \
  --json-prefill \
  --output data/results/colab/qlora/base_eval.json
```

```python
!PYTHONPATH=src python scripts/evaluate_finetuned_model.py \
  --split data/finetuning/test.jsonl \
  --max-new-tokens 4096 \
  --json-prefill \
  --adapter /content/drive/MyDrive/ai-presales-lab-results/active-training \
  --output data/results/colab/qlora/adapter_eval.json
```

至少记录：

- `json_parse_rate`：输出是否是可解析 JSON。
- `schema_pass_rate`：是否满足解决方案 schema。
- `policy_pass_rate`：是否通过输出和敏感数据策略。
- `conservative_no_evidence`：证据不足时是否保守回答。
- train/eval loss、训练时间、GPU 型号、显存峰值、是否 OOM。

如果 base 和 adapter 的严格 JSON 通过率都为 0，先运行短诊断而不是立即修改指标定义。诊断只保存每个模型前 3 条、最多 800 字符的生成预览；正式报告默认不保存原始生成文本，以减少隐私泄露风险：

```python
!PYTHONPATH=src python scripts/evaluate_finetuned_model.py \
  --model Qwen/Qwen2.5-0.5B-Instruct \
  --split data/finetuning/test.jsonl \
  --limit 3 \
  --max-new-tokens 4096 \
  --json-prefill \
  --include-output-previews \
  --preview-chars 800 \
  --output data/results/colab/qlora/base-diagnostic.json
```

再对 adapter 执行同样的命令并增加 `--adapter`。检查 `output_preview`、`output_chars` 和 `error`：不要为了让分数变高而直接从 Markdown 或解释性文本中“抢救” JSON；正式 schema 指标仍应要求模型输出严格 JSON。

不要只看训练 loss。若 adapter 在训练集上变好、held-out test 变差，说明可能过拟合；若结构化输出变好但证据或安全策略变差，也不能称为整体效果提升。

## 5. 常见问题处理

| 现象 | 处理顺序 |
| --- | --- |
| `torch.cuda.is_available()=False` | 这不是 QLoRA 脚本错误：先执行 Runtime → Change runtime type → GPU，保存并重新连接 runtime；如果仍无法分配，免费 Colab 的 GPU 可能暂时不可用，稍后重试。若诊断中的 `cuda_runtime` 为 `null`，不要手动装 CPU 版 torch，重启 runtime 后重新运行 notebook 安装单元格 |
| `bitsandbytes` 找不到 CUDA | 确认是 Linux NVIDIA runtime；重启 runtime 后重新安装 `finetune-colab`，不要安装 CPU 版 torch |
| `CUDA out of memory` | 先将 `LOW_MEMORY=True` 或改用 `trl_qlora_colab_lowmem.json`；仍失败时优先降低 batch size，再根据 token audit 评估是否能把 max length 降到 3072；保留日志并披露截断风险 |
| 训练后输出目录找不到 | 先确认 Drive 是否挂载；检查 `active-training/checkpoint-*` 和 `adapter_config.json` |
| Hugging Face 下载超时 | 重新运行下载单元格；不要把 Token 写入 notebook。公开模型不需要 Token |
| TRL 参数不兼容 | 重启 runtime，重新运行安装；保留 `pip-freeze.txt` 和完整错误。不要静默修改训练参数后声称可复现 |
| `No columns in the dataset match ... prompt, completion` | 这是旧脚本把 raw held-out split 直接传给底层 `Trainer.evaluate` 的问题；从仓库拉取最新脚本，让 evaluation-only `SFTTrainer` 先完成同一套 SFT preprocessing，不要改成 `remove_unused_columns=False` |
| adapter 评估只显示 `CalledProcessError` | 这是 notebook 外层 subprocess 丢弃了真实 stderr；最新版会分别保存 `base-eval.log` 和 `adapter-eval.log`。先打开 adapter 日志，并检查 `adapter_config.json` 与 `adapter_model.safetensors/bin` 是否存在 |
| `base-eval` 成功但 `adapter-eval` 失败 | 重点检查 adapter 目录是否为正式训练输出根目录、`base_model_name_or_path` 是否仍为 `Qwen/Qwen2.5-0.5B-Instruct`、PEFT 版本是否来自当前 runtime；不要把 `smoke-test/` 或 checkpoint-<step> 目录直接当作最终 adapter |
| `Found an incompatible version of torchao` | 本项目不使用 TorchAO，通常是 Colab 预装的旧 `torchao` 被 PEFT 探测到。删除/重启 runtime，从最新版 notebook 重新运行安装单元；该单元会卸载 TorchAO。不要用 `torchao==0.10.0` 继续评估；若其他项目确实需要 TorchAO，应按当前 PyTorch 版本选择兼容版本 |
| Colab runtime 断开 | 重新挂载 Drive，使用最新 checkpoint 的 `--resume-from-checkpoint`；若没有 checkpoint，只能重新训练 |
| JSON parse rate 很低 | 先检查 max_new_tokens、chat template 和 prompt/completion loss 模式，再判断是否需要增加数据或调整训练，不要直接修改 test 结果 |
| `generation_truncated` 很高 | 生成预算不足或模型没有在 EOS 结束；先使用 4096/更高预算并检查 output preview，不能把被截断的 JSON 计为 schema 通过 |
| token audit 报 overflow | `max_length` 包含 prompt 和 assistant target；提高上下文上限或进一步压缩 target/context，重新生成 manifest 后再训练 |

## 6. 你最终应下载/保存的文件

建议从 Drive 或 notebook 生成的 zip 中保留：

```text
runtime.json
pip-freeze.txt
trl_qlora.json
manifest.json
base_eval.json
adapter_eval.json
adapter/adapter_config.json
adapter/adapter_model.safetensors
adapter/metrics.json
```

将 `base_eval.json`、`adapter_eval.json`、`runtime.json` 和 `metrics.json` 下载回本地仓库的 `data/results/colab/qlora/` 后，再决定是否提交。模型权重和 checkpoint 可以只保存在 Drive，不必提交到 GitHub。

## 7. 简历可使用的结果口径

只有在真实训练和 test 对比完成后，才可以写：

> 在 Colab `[GPU 型号]` 上使用 Qwen2.5-0.5B-Instruct 完成 NF4 QLoRA 训练，记录训练耗时 `[X]`、峰值显存 `[Y]`；在固定 held-out test split 上，base/adapter 的 JSON parse、schema 和 policy 指标分别为 `[结果]`。

如果只完成 dry-run，应写：

> 完成 ShareGPT 数据构建、case-level split、manifest/hash、TRL/PEFT QLoRA 训练入口、LLaMA Factory 配置和 Colab 可复现实验流程，已通过 dry-run；真实 GPU 训练结果待补充。

不要把 Colab 单次实验结果写成通用模型能力、生产 SLA、客户 KPI 或所有 GPU 都适用的性能结论。适配器部署到真实服务或导出 GGUF 前，仍需重新跑质量、安全、并发、延迟和成本回归。
