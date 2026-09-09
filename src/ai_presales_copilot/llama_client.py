"""OpenAI-compatible llama.cpp client implemented with the Python standard library."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


class LlamaClientError(RuntimeError):
    """Raised when llama.cpp is unavailable or returns an invalid response."""


@dataclass(frozen=True)
class GenerationResult:
    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    latency_ms: float
    time_to_first_token_ms: float | None = None


class LlamaClient:
    def __init__(
        self, base_url: str | None = None, model: str | None = None, timeout_s: float = 120
    ):
        self.base_url = (base_url or os.getenv("LLAMA_BASE_URL", "http://127.0.0.1:8080")).rstrip(
            "/"
        )
        self.model = model or os.getenv("LLAMA_MODEL", "local-model")
        self.timeout_s = timeout_s

    def health(self) -> dict[str, Any]:
        request = urllib.request.Request(f"{self.base_url}/health", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return {"status": response.status, "body": response.read().decode("utf-8")}
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LlamaClientError(f"llama.cpp health check failed: {exc}") from exc

    def chat(
        self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 256
    ) -> GenerationResult:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        started = time.perf_counter()
        body = self._post("/v1/chat/completions", payload)
        latency_ms = (time.perf_counter() - started) * 1000
        choice = (body.get("choices") or [{}])[0]
        usage = body.get("usage", {})
        return GenerationResult(
            text=choice.get("message", {}).get("content", ""),
            model=body.get("model", self.model),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=round(latency_ms, 2),
        )

    def chat_stream(
        self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 256
    ) -> GenerationResult:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        started = time.perf_counter()
        first_token_at: float | None = None
        chunks: list[str] = []
        usage: dict[str, Any] = {}
        for event in self._post_sse("/v1/chat/completions", payload):
            if event == "[DONE]":
                continue
            try:
                chunk = json.loads(event)
            except json.JSONDecodeError:
                continue
            delta = ((chunk.get("choices") or [{}])[0]).get("delta", {})
            text = delta.get("content", "") or ""
            if text and first_token_at is None:
                first_token_at = time.perf_counter()
            chunks.append(text)
            usage.update(chunk.get("usage") or {})
        ended = time.perf_counter()
        return GenerationResult(
            text="".join(chunks),
            model=self.model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=round((ended - started) * 1000, 2),
            time_to_first_token_ms=round((first_token_at - started) * 1000, 2)
            if first_token_at
            else None,
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LlamaClientError(f"llama.cpp HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LlamaClientError(f"llama.cpp request failed: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LlamaClientError("llama.cpp returned invalid JSON") from exc

    def _post_sse(self, path: str, payload: dict[str, Any]) -> Iterator[str]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if line.startswith("data:"):
                        yield line.removeprefix("data:").strip()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LlamaClientError(f"llama.cpp streaming HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LlamaClientError(f"llama.cpp streaming request failed: {exc}") from exc
