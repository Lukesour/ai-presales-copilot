#!/usr/bin/env python3
"""Start the local llama.cpp, Presales API and Gradio demo as one process tree."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from local_demo_runtime import (
    DEFAULT_API_PORT,
    DEFAULT_CONTEXT,
    DEFAULT_GPU_LAYERS,
    DEFAULT_HOST,
    DEFAULT_LLAMA_PORT,
    DEFAULT_MODEL_ALIAS,
    DEFAULT_MODEL_PATH,
    DEFAULT_UI_PORT,
    ROOT,
    Settings,
    StartupError,
    run,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("PRESALES_LOCAL_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--model-path",
        default=os.getenv("PRESALES_MODEL_PATH", DEFAULT_MODEL_PATH),
        help="GGUF path, relative to the repository root unless absolute.",
    )
    parser.add_argument(
        "--model-alias",
        default=os.getenv("PRESALES_MODEL_ALIAS", DEFAULT_MODEL_ALIAS),
    )
    parser.add_argument(
        "--llama-port",
        type=int,
        default=int(os.getenv("PRESALES_LLAMA_PORT", str(DEFAULT_LLAMA_PORT))),
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=int(os.getenv("PRESALES_API_PORT", str(DEFAULT_API_PORT))),
    )
    parser.add_argument(
        "--ui-port",
        type=int,
        default=int(os.getenv("PRESALES_UI_PORT", str(DEFAULT_UI_PORT))),
    )
    parser.add_argument(
        "--ctx-size",
        type=int,
        default=int(os.getenv("PRESALES_CTX_SIZE", str(DEFAULT_CONTEXT))),
    )
    parser.add_argument(
        "--gpu-layers",
        type=int,
        default=int(os.getenv("PRESALES_GPU_LAYERS", str(DEFAULT_GPU_LAYERS))),
    )
    parser.add_argument(
        "--dev-token",
        default=os.getenv("PRESALES_DEV_TOKEN", os.getenv("PRESALES_API_TOKEN", "dev-token")),
        help="Local-only token passed through the child environment; do not use in production.",
    )
    return parser


def resolve_settings(args: argparse.Namespace) -> Settings:
    model_path = Path(args.model_path)
    if not model_path.is_absolute():
        model_path = ROOT / model_path
    if not model_path.is_file():
        raise StartupError(
            f"Model file does not exist: {model_path}\n"
            "Download or place the GGUF file under models/, or pass --model-path."
        )
    ports = (args.llama_port, args.api_port, args.ui_port)
    if len(set(ports)) != len(ports):
        raise StartupError("--llama-port, --api-port and --ui-port must be different.")
    if any(port < 1 or port > 65535 for port in ports):
        raise StartupError("All ports must be between 1 and 65535.")
    if args.ctx_size < 1 or args.gpu_layers < 0:
        raise StartupError("--ctx-size must be positive and --gpu-layers cannot be negative.")
    if not args.model_alias.strip():
        raise StartupError("--model-alias cannot be empty.")
    return Settings(
        host=args.host,
        model_path=model_path,
        model_alias=args.model_alias.strip(),
        llama_port=args.llama_port,
        api_port=args.api_port,
        ui_port=args.ui_port,
        context_size=args.ctx_size,
        gpu_layers=args.gpu_layers,
        dev_token=args.dev_token,
    )


def main() -> int:
    try:
        return run(resolve_settings(build_parser().parse_args()))
    except StartupError as exc:
        print(f"startup error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
