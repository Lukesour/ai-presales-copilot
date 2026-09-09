#!/usr/bin/env python3
"""Benchmark a running llama.cpp OpenAI-compatible server."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ai_presales_copilot.llama_client import LlamaClient, LlamaClientError

ROOT = Path(__file__).resolve().parents[1]


PROMPTS = [
    "请用 JSON 输出：客户要求内网部署、数据不能出域、峰值 5 并发。请列出需要澄清的三个问题。",
    "请用 JSON 比较云端 API 与本地量化模型在数据安全、延迟、成本和运维方面的取舍。",
    "请用 JSON 输出一个企业知识库 PoC 的四步实施计划，并标记不能直接承诺的指标。",
    "请用 JSON 判断：只有一台 Apple Silicon 工作站是否可以直接承诺 100 并发生产服务？说明理由。",
    "请用 JSON 输出模型量化评测报告应包含的字段。不要编造任何实际数值。",
]


def one_request(client: LlamaClient, prompt: str, stream: bool) -> dict[str, object]:
    started = time.perf_counter()
    try:
        messages = [
            {"role": "system", "content": "你是严谨的 AI 基础设施售前顾问，只输出有效 JSON。"},
            {"role": "user", "content": prompt},
        ]
        result = (
            client.chat_stream(messages, max_tokens=256)
            if stream
            else client.chat(messages, max_tokens=256)
        )
        elapsed = (time.perf_counter() - started) * 1000
        tokens = result.completion_tokens
        valid_json = _is_json(result.text)
        return {
            "ok": True,
            "latency_ms": round(elapsed, 2),
            "ttft_ms": result.time_to_first_token_ms,
            "completion_tokens": tokens,
            "tokens_per_second": round(tokens / (elapsed / 1000), 2)
            if tokens and elapsed
            else None,
            "text_chars": len(result.text),
            "valid_json": valid_json,
        }
    except LlamaClientError as exc:
        return {
            "ok": False,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--requests", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--no-stream", action="store_true")
    parser.add_argument("--label", default="unlabeled")
    parser.add_argument("--model-path", type=Path, default=None)
    parser.add_argument("--context", type=int, default=None)
    parser.add_argument("--gpu-layers", type=int, default=None)
    parser.add_argument(
        "--server-pid", type=int, default=None, help="PID of llama-server for RSS sampling"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be positive")
    client = LlamaClient(base_url=args.base_url)
    jobs = [PROMPTS[index % len(PROMPTS)] for index in range(args.requests)]
    started = time.perf_counter()
    results: list[dict[str, object]] = []
    monitor = RssMonitor(args.server_pid) if args.server_pid else None
    if monitor:
        monitor.start()
    gpu_monitor = GpuMemoryMonitor(args.server_pid) if args.server_pid else None
    if gpu_monitor:
        gpu_monitor.start()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(one_request, client, prompt, not args.no_stream) for prompt in jobs]
        for future in as_completed(futures):
            results.append(future.result())
    if monitor:
        monitor.stop()
    if gpu_monitor:
        gpu_monitor.stop()
    wall_ms = round((time.perf_counter() - started) * 1000, 2)
    successful = [result for result in results if result.get("ok")]
    latencies = [float(result["latency_ms"]) for result in successful]
    ttfts = [float(result["ttft_ms"]) for result in successful if result.get("ttft_ms") is not None]
    valid_json_count = sum(bool(result.get("valid_json")) for result in successful)
    completion_tokens = sum(
        int(result["completion_tokens"])
        for result in successful
        if result.get("completion_tokens") is not None
    )
    wall_seconds = wall_ms / 1000
    report = {
        "label": args.label,
        "base_url": client.base_url,
        "model": _model_metadata(args.model_path),
        "environment": _environment_metadata(),
        "runtime": {
            "context": args.context,
            "gpu_layers": args.gpu_layers,
        },
        "requests": args.requests,
        "concurrency": args.concurrency,
        "streaming": not args.no_stream,
        "wall_time_ms": wall_ms,
        "success": len(successful),
        "failure": len(results) - len(successful),
        "completion_tokens": completion_tokens,
        "throughput_tokens_per_second": round(completion_tokens / wall_seconds, 2)
        if completion_tokens and wall_seconds
        else None,
        "structured_json_pass": valid_json_count,
        "structured_json_pass_rate": round(valid_json_count / len(successful), 4)
        if successful
        else 0.0,
        "latency_ms": _stats(latencies),
        "ttft_ms": _stats(ttfts),
        "server_memory_mib": monitor.stats() if monitor else None,
        "gpu_memory_mib": gpu_monitor.stats() if gpu_monitor else None,
        "results": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if len(successful) == args.requests else 1


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p95": None, "min": None, "max": None}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))
    return {
        "count": len(values),
        "mean": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
        "p95": round(ordered[p95_index], 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }


def _is_json(text: str) -> bool:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.removeprefix("```").removeprefix("json").removesuffix("```").strip()
    try:
        json.loads(candidate)
    except json.JSONDecodeError:
        return False
    return True


def _model_metadata(model_path: Path | None) -> dict[str, object] | None:
    if model_path is None:
        return None
    metadata: dict[str, object] = {"path": str(model_path)}
    if model_path.exists():
        metadata["file_size_mib"] = round(model_path.stat().st_size / (1024 * 1024), 2)
        metadata["sha256"] = _sha256(model_path)
    lower_name = model_path.name.lower()
    for quantization in ("q2", "q3", "q4", "q5", "q6", "q8", "f16", "bf16"):
        if quantization in lower_name:
            metadata["quantization"] = quantization.upper()
            break
    return metadata


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class RssMonitor:
    """Sample the llama-server resident set size without third-party packages."""

    def __init__(self, pid: int, interval_s: float = 0.05):
        self.pid = pid
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._samples: list[float] = []

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="rss-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def stats(self) -> dict[str, float | None]:
        if not self._samples:
            return {"samples": 0, "before_mib": None, "peak_mib": None, "after_mib": None}
        return {
            "samples": len(self._samples),
            "before_mib": round(self._samples[0], 2),
            "peak_mib": round(max(self._samples), 2),
            "after_mib": round(self._samples[-1], 2),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            rss_mib = _rss_mib(self.pid)
            if rss_mib is not None:
                self._samples.append(rss_mib)
            self._stop.wait(self.interval_s)


class GpuMemoryMonitor(RssMonitor):
    """Sample llama-server VRAM usage through nvidia-smi when available."""

    def __init__(self, pid: int, interval_s: float = 0.2):
        super().__init__(pid, interval_s)
        self._command_available = shutil.which("nvidia-smi") is not None

    def _run(self) -> None:
        if not self._command_available:
            return
        while not self._stop.is_set():
            gpu_mib = _gpu_rss_mib(self.pid)
            if gpu_mib is not None:
                self._samples.append(gpu_mib)
            self._stop.wait(self.interval_s)


def _environment_metadata() -> dict[str, object]:
    metadata: dict[str, object] = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
    }
    gpu_info = _nvidia_gpu_info()
    if gpu_info:
        metadata["nvidia"] = gpu_info
    for key in ("LLAMA_CPP_COMMIT", "LLAMA_CPP_VERSION", "MODEL_REPO", "MODEL_REVISION"):
        value = os.getenv(key)
        if value:
            metadata[key.lower()] = value
    return metadata


def _nvidia_gpu_info() -> dict[str, str] | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,compute_cap",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not output:
        return None
    fields = [field.strip() for field in output.splitlines()[0].split(",")]
    if len(fields) != 4:
        return None
    return {
        "name": fields[0],
        "driver_version": fields[1],
        "memory_total_mib": fields[2],
        "compute_capability": fields[3],
    }


def _rss_mib(pid: int) -> float | None:
    try:
        output = subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)], text=True).strip()
        rss_kib = int(output)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None
    return rss_kib / 1024


def _gpu_rss_mib(pid: int) -> float | None:
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in output.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 2:
            continue
        try:
            if int(fields[0]) == pid:
                return float(fields[1])
        except ValueError:
            continue
    return 0.0


if __name__ == "__main__":
    raise SystemExit(main())
