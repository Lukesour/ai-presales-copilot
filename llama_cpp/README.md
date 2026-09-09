# llama.cpp 本地推理复现

本目录验证模型基础设施能力：运行量化 GGUF 模型，暴露 OpenAI-compatible 接口，并用实测数据讨论部署取舍。

## 上游项目

- 仓库：[ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)
- 官方说明支持 Apple Silicon、Metal 和 GGUF 量化模型
- 本作品集不提交模型文件；模型许可证和使用范围需要单独核查

## 推荐路径：Colab GPU 实测

使用 [`notebooks/llama_cpp_colab_benchmark.ipynb`](../notebooks/llama_cpp_colab_benchmark.ipynb) 运行一次完整的 CUDA Q4/Q8 对比。它不会把 llama-server 暴露到公网，且会把模型 revision、SHA-256、GPU、驱动、延迟、TTFT、聚合吞吐、CPU RSS 和 GPU VRAM 一起记录。运行协议与 Colab 限制见 [`docs/colab-runbook.md`](../docs/colab-runbook.md)。

## macOS 原生构建（本机 smoke test）

```bash
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
cmake -B build -DGGML_METAL=ON
cmake --build build --config Release -t llama-server llama-cli
```

把 `LLAMA_SERVER_BIN` 指向 `build/bin/llama-server`。模型可以使用官方支持的 Hugging Face GGUF 仓库，建议先选小模型验证流程：

```bash
cd ai-presales-copilot
LLAMA_CLI_BIN=/path/to/llama-cli ./scripts/download_model.sh
```

脚本会下载模型并做一次最小 smoke test。不要把模型文件提交到仓库。

## 启动服务

```bash
export LLAMA_SERVER_BIN=/path/to/llama-server
export LLAMA_MODEL_PATH=/path/to/model.Q4_K_M.gguf
./scripts/start_llama_server.sh
```

服务默认地址为 `http://127.0.0.1:8080`。原生 macOS 构建用于观察 Metal 性能；如果只需要跨环境 API smoke test，也可以使用官方 arm64 Docker 镜像，但容器模式不等价于 Metal 加速。

## 性能评测

```bash
PYTHONPATH=src python3 scripts/benchmark_llama.py \
  --label q4-metal-c1 \
  --requests 5 \
  --concurrency 1 \
  --output data/results/q4-metal-c1.json
```

如果需要记录服务进程内存，先获取 `llama-server` 的 PID，再增加 `--server-pid`：

```bash
LLAMA_PID=$(pgrep -n llama-server)
PYTHONPATH=src python3 scripts/benchmark_llama.py \
  --label q4-metal-c4 \
  --requests 8 \
  --concurrency 4 \
  --server-pid "$LLAMA_PID" \
  --output data/results/q4-metal-c4.json
```

重复运行 Q4/Q5/Q8、CPU/Metal、单请求/并发 4 和不同上下文长度，记录模型文件、硬件、启动参数和日期。最终只引用 `data/results/` 中实际生成的数据。

benchmark JSON 还包含 `throughput_tokens_per_second`、`server_memory_mib`、`gpu_memory_mib` 和环境元数据；使用 `scripts/summarize_benchmarks.py` 可将同一批 Q4/Q8 报告汇总。
