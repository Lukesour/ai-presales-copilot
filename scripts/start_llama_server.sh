#!/usr/bin/env bash
set -euo pipefail

LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-llama-server}"
LLAMA_MODEL_PATH="${LLAMA_MODEL_PATH:-}"
LLAMA_CONTEXT="${LLAMA_CONTEXT:-4096}"
LLAMA_GPU_LAYERS="${LLAMA_GPU_LAYERS:-999}"
LLAMA_HOST="${LLAMA_HOST:-127.0.0.1}"
LLAMA_PORT="${LLAMA_PORT:-8080}"
LLAMA_MODEL_ALIAS="${LLAMA_MODEL_ALIAS:-${LLAMA_MODEL:-local-qwen}}"
LLAMA_API_KEY="${LLAMA_API_KEY:-}"

if [[ -z "$LLAMA_MODEL_PATH" ]]; then
  echo "Set LLAMA_MODEL_PATH to a local .gguf file before starting the server." >&2
  exit 2
fi
if ! command -v "$LLAMA_SERVER_BIN" >/dev/null 2>&1; then
  echo "Cannot find $LLAMA_SERVER_BIN. Build llama.cpp or set LLAMA_SERVER_BIN to its absolute path." >&2
  exit 2
fi
if [[ ! -f "$LLAMA_MODEL_PATH" ]]; then
  echo "Model file does not exist: $LLAMA_MODEL_PATH" >&2
  exit 2
fi

echo "Starting llama.cpp on http://${LLAMA_HOST}:${LLAMA_PORT}"
echo "model=${LLAMA_MODEL_PATH} alias=${LLAMA_MODEL_ALIAS} context=${LLAMA_CONTEXT} gpu_layers=${LLAMA_GPU_LAYERS}"
LLAMA_EXTRA_ARGS=()
if [[ -n "$LLAMA_MODEL_ALIAS" ]]; then
  LLAMA_EXTRA_ARGS+=(--alias "$LLAMA_MODEL_ALIAS")
fi
if [[ -n "$LLAMA_API_KEY" ]]; then
  LLAMA_EXTRA_ARGS+=(--api-key "$LLAMA_API_KEY")
fi
exec "$LLAMA_SERVER_BIN" \
  -m "$LLAMA_MODEL_PATH" \
  -c "$LLAMA_CONTEXT" \
  -ngl "$LLAMA_GPU_LAYERS" \
  --host "$LLAMA_HOST" \
  --port "$LLAMA_PORT" \
  "${LLAMA_EXTRA_ARGS[@]}"
