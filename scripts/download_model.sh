#!/usr/bin/env bash
set -euo pipefail

LLAMA_CLI_BIN="${LLAMA_CLI_BIN:-llama-cli}"
MODEL_REPO="${1:-Qwen/Qwen3-8B-GGUF}"
MODEL_QUANT="${2:-Q4_K_M}"

if ! command -v "$LLAMA_CLI_BIN" >/dev/null 2>&1; then
  echo "Cannot find $LLAMA_CLI_BIN. Build llama.cpp first." >&2
  exit 2
fi

echo "This downloads/loads the configured GGUF model and runs a one-token smoke test."
echo "The 0.5B model is smoke-test-only; the Phase 1 solution baseline is Qwen3-8B Q4."
echo "Model repository: $MODEL_REPO"
echo "Quantization: $MODEL_QUANT"
"$LLAMA_CLI_BIN" -hf "$MODEL_REPO:$MODEL_QUANT" -n 1 -p "Reply with OK."
