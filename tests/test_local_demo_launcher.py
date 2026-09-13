from pathlib import Path

from scripts.local_demo_runtime import (
    Settings,
    build_api_command,
    build_llama_command,
    build_ui_command,
)


def _settings() -> Settings:
    return Settings(
        host="127.0.0.1",
        model_path=Path("models/Qwen3-1.7B-Q4_K_M.gguf"),
        model_alias="qwen3-1.7b-demo",
        llama_port=18080,
        api_port=18090,
        ui_port=17860,
        context_size=8192,
        gpu_layers=999,
        dev_token="dev-token",
    )


def test_launcher_keeps_model_identity_consistent_across_processes():
    settings = _settings()
    llama = build_llama_command(settings, "/usr/local/bin/llama-server")
    api = build_api_command(settings, "/usr/local/bin/uv")

    assert llama[llama.index("--alias") + 1] == "qwen3-1.7b-demo"
    assert api[api.index("--model") + 1] == "qwen3-1.7b-demo"
    assert api[api.index("--llama-url") + 1] == "http://127.0.0.1:18080"


def test_launcher_uses_fixed_ports_and_live_api_for_gradio():
    command = build_ui_command(_settings(), "/usr/local/bin/uv")

    assert "--initial-mode" not in command
    assert command[command.index("--mode") + 1] == "api"
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "17860"
