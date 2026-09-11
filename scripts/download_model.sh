#!/usr/bin/env bash
set -euo pipefail

MODEL_REPO="${1:-Qwen/Qwen3-8B-GGUF}"
MODEL_QUANT="${2:-Q4_K_M}"
MODEL_DIR="${MODEL_DIR:-models}"
MODEL_FILE="${MODEL_FILE:-Qwen3-8B-${MODEL_QUANT}.gguf}"

if command -v hf >/dev/null 2>&1; then
  HF_BIN="hf"
elif command -v huggingface-cli >/dev/null 2>&1; then
  HF_BIN="huggingface-cli"
else
  echo "Install the Hugging Face CLI first (hf or huggingface-cli)." >&2
  exit 2
fi

mkdir -p "$MODEL_DIR"
echo "Downloading the Phase 1 local model; weights are never committed to Git."
echo "Model repository: $MODEL_REPO"
echo "Quantization: $MODEL_QUANT"
echo "Destination: $MODEL_DIR/$MODEL_FILE"

if [[ "$HF_BIN" == "hf" ]]; then
  hf download "$MODEL_REPO" "$MODEL_FILE" --local-dir "$MODEL_DIR"
else
  huggingface-cli download "$MODEL_REPO" "$MODEL_FILE" --local-dir "$MODEL_DIR"
fi

MODEL_PATH="$MODEL_DIR/$MODEL_FILE"
if [[ ! -f "$MODEL_PATH" ]]; then
  echo "Downloaded model file not found: $MODEL_PATH" >&2
  exit 3
fi

if command -v shasum >/dev/null 2>&1; then
  MODEL_SHA256="$(shasum -a 256 "$MODEL_PATH" | awk '{print $1}')"
else
  MODEL_SHA256="$(sha256sum "$MODEL_PATH" | awk '{print $1}')"
fi
echo "LLAMA_MODEL_FILE=$MODEL_FILE"
echo "LLAMA_MODEL_SHA256=$MODEL_SHA256"
echo "Copy the hash into .env before sharing the Compose deployment."
