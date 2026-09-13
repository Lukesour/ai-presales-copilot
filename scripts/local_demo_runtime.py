"""Process-tree and readiness helpers for the local demo launcher."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = "models/Qwen3-1.7B-Q4_K_M.gguf"
DEFAULT_MODEL_ALIAS = "qwen3-1.7b-demo"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_LLAMA_PORT = 8080
DEFAULT_API_PORT = 8090
DEFAULT_UI_PORT = 7860
DEFAULT_CONTEXT = 8192
DEFAULT_GPU_LAYERS = 999

@dataclass(frozen=True)
class Settings:
    """Resolved local demo settings shared by all child processes."""

    host: str
    model_path: Path
    model_alias: str
    llama_port: int
    api_port: int
    ui_port: int
    context_size: int
    gpu_layers: int
    dev_token: str

    @property
    def local_host(self) -> str:
        return "127.0.0.1" if self.host in {"0.0.0.0", "::"} else self.host

    @property
    def model_url(self) -> str:
        return f"http://{self.local_host}:{self.llama_port}"

    @property
    def api_url(self) -> str:
        return f"http://{self.local_host}:{self.api_port}"

class StartupError(RuntimeError):
    """Raised when a dependency cannot be started or become ready."""
def build_llama_command(settings: Settings, executable: str) -> list[str]:
    return [
        executable,
        "-m",
        str(settings.model_path),
        "--host",
        settings.host,
        "--port",
        str(settings.llama_port),
        "--ctx-size",
        str(settings.context_size),
        "--gpu-layers",
        str(settings.gpu_layers),
        "--alias",
        settings.model_alias,
        "--jinja",
        "--reasoning",
        "off",
    ]
def build_api_command(settings: Settings, uv_executable: str) -> list[str]:
    return [
        uv_executable,
        "run",
        "--locked",
        "--extra",
        "runtime",
        "python",
        "scripts/serve_agent.py",
        "--allow-dev-auth",
        "--host",
        settings.host,
        "--port",
        str(settings.api_port),
        "--llama-url",
        settings.model_url,
        "--model",
        settings.model_alias,
        "--model-path",
        str(settings.model_path),
    ]

def build_ui_command(settings: Settings, uv_executable: str) -> list[str]:
    return [
        uv_executable,
        "run",
        "--locked",
        "--extra",
        "runtime",
        "--extra",
        "demo",
        "python",
        "demo/gradio_app.py",
        "--mode",
        "api",
        "--host",
        settings.host,
        "--port",
        str(settings.ui_port),
    ]

def _check_port(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise StartupError(
                f"Port {host}:{port} is already in use. Stop the old service or "
                "pass a different port."
            ) from exc

def _probe_json(url: str, timeout_s: float = 2.0) -> tuple[int | None, dict[str, Any]]:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload if isinstance(payload, dict) else {"data": payload}
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"error": str(exc)}
        return exc.code, payload if isinstance(payload, dict) else {"data": payload}
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, {"error": str(exc)}

def _probe_status(url: str, timeout_s: float = 2.0) -> int | None:
    try:
        with urlopen(Request(url, headers={"Accept": "text/html"}), timeout=timeout_s) as response:
            return response.status
    except HTTPError as exc:
        return exc.code
    except (OSError, URLError, TimeoutError):
        return None

def _wait_for_model(settings: Settings, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 90
    url = f"{settings.model_url}/v1/models"
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise StartupError(f"llama-server exited before readiness (code {process.returncode}).")
        _, payload = _probe_json(url)
        last = payload
        entries = payload.get("data") or []
        model_ids = [str(item.get("id")) for item in entries if isinstance(item, dict)]
        if settings.model_alias in model_ids:
            return
        time.sleep(0.5)
    raise StartupError(f"llama-server did not expose model {settings.model_alias}: {last}")

def _wait_for_api(settings: Settings, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 90
    url = f"{settings.api_url}/readyz"
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise StartupError(f"Presales API exited before readiness (code {process.returncode}).")
        status, payload = _probe_json(url)
        last = payload
        if status == 200 and payload.get("status") == "ready":
            return
        time.sleep(0.5)
    raise StartupError(f"Presales API did not become ready: {last}")

def _wait_for_ui(settings: Settings, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    url = f"http://{settings.local_host}:{settings.ui_port}/"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise StartupError(f"Gradio exited before listening (code {process.returncode}).")
        status = _probe_status(url)
        if status is not None and status < 500:
            return
        time.sleep(0.5)
    raise StartupError(f"Gradio did not become reachable at {url}.")

def _terminate(processes: list[tuple[str, subprocess.Popen[bytes]]]) -> None:
    for _, process in reversed(processes):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (AttributeError, ProcessLookupError, PermissionError):
                process.terminate()
    deadline = time.monotonic() + 8
    for _, process in reversed(processes):
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (AttributeError, ProcessLookupError, PermissionError):
                    process.kill()

def _child_env(settings: Settings) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(ROOT / "src"), str(ROOT), environment.get("PYTHONPATH", ""))
    ).strip(os.pathsep)
    environment.update(
        {
            "PRESALES_ALLOW_DEV_AUTH": "true",
            "PRESALES_DEV_TOKEN": settings.dev_token,
            "PRESALES_API_URL": settings.api_url,
            "PRESALES_API_TOKEN": settings.dev_token,
        }
    )
    return environment

def run(settings: Settings) -> int:
    llama_bin = shutil.which(os.getenv("LLAMA_SERVER_BIN", "llama-server"))
    uv_bin = shutil.which(os.getenv("UV_BIN", "uv"))
    if llama_bin is None:
        raise StartupError(
            "Cannot find llama-server. Install/build llama.cpp or set LLAMA_SERVER_BIN."
        )
    if uv_bin is None:
        raise StartupError("Cannot find uv. Install uv before using the one-terminal launcher.")
    for port in (settings.llama_port, settings.api_port, settings.ui_port):
        _check_port(settings.host, port)

    environment = _child_env(settings)
    processes: list[tuple[str, subprocess.Popen[bytes]]] = []

    def request_stop(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    old_handlers = {
        signal.SIGINT: signal.getsignal(signal.SIGINT),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
    }
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    try:
        print(f"[llama] starting on {settings.model_url} as {settings.model_alias}", flush=True)
        llama = subprocess.Popen(
            build_llama_command(settings, llama_bin),
            cwd=ROOT,
            env=environment,
            start_new_session=True,
        )
        processes.append(("llama-server", llama))
        _wait_for_model(settings, llama)
        print("[llama] ready", flush=True)

        print(f"[api] starting on {settings.api_url}", flush=True)
        api = subprocess.Popen(
            build_api_command(settings, uv_bin),
            cwd=ROOT,
            env=environment,
            start_new_session=True,
        )
        processes.append(("presales-api", api))
        _wait_for_api(settings, api)
        print("[api] ready", flush=True)

        print(f"[ui] starting on http://{settings.local_host}:{settings.ui_port}", flush=True)
        ui = subprocess.Popen(
            build_ui_command(settings, uv_bin),
            cwd=ROOT,
            env=environment,
            start_new_session=True,
        )
        processes.append(("gradio", ui))
        _wait_for_ui(settings, ui)
        print("[ui] ready; press Ctrl-C to stop all three services", flush=True)

        while True:
            for name, process in processes:
                if process.poll() is not None:
                    raise StartupError(f"{name} exited unexpectedly (code {process.returncode}).")
            time.sleep(0.25)
    finally:
        _terminate(processes)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    return 0
