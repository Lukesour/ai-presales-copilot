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
        self.model_hash = os.getenv("LLAMA_MODEL_SHA256")
        self.quantization = os.getenv("LLAMA_QUANTIZATION", "Q4_K_M")
        self.context_length = int(os.getenv("LLAMA_CONTEXT", "8192"))
        self.llama_cpp_commit = os.getenv("LLAMA_CPP_COMMIT")

    def health(self) -> dict[str, Any]:
        request = urllib.request.Request(f"{self.base_url}/health", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return {"status": response.status, "body": response.read().decode("utf-8")}
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LlamaClientError(f"llama.cpp health check failed: {exc}") from exc

    def readiness(self) -> dict[str, Any]:
        """Verify that the server is healthy and exposes the configured model."""

        try:
            health = self.health()
        except LlamaClientError:
            return {
                "status": "not_ready",
                "error_code": "model_unavailable",
                "detail": "llama-server /health is unavailable",
            }
        if health.get("status") != 200:
            return {
                "status": "not_ready",
                "error_code": f"http_{health.get('status')}",
            }
        try:
            catalog = self._get("/v1/models")
        except LlamaClientError:
            return {
                "status": "not_ready",
                "error_code": "model_catalog_unavailable",
                "detail": "llama-server /v1/models is unavailable",
            }
        available_models = _model_ids(catalog)
        if not available_models:
            return {
                "status": "not_ready",
                "error_code": "model_catalog_empty",
                "configured_model": self.model,
            }
        if self.model not in available_models:
            return {
                "status": "not_ready",
                "error_code": "model_mismatch",
                "configured_model": self.model,
                "available_models": available_models,
            }
        return {
            "status": "ready",
            "model": self.model,
            "available_models": available_models,
        }

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 256,
        response_schema: dict[str, Any] | None = None,
        json_mode: bool = False,
    ) -> GenerationResult:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if response_schema is not None:
            wire_schema = _inline_local_refs(response_schema)
            # llama.cpp supports its schema-constrained path through a JSON
            # object response plus the top-level ``json_schema`` extension.
            # Do not send ``type=json_schema`` and the top-level extension at
            # the same time: several server builds compile both grammar
            # definitions and fail with ``Failed to initialize samplers``.
            # The caller still validates the body after HTTP 200 because a
            # compatible server may accept the request without enforcing it.
            payload["response_format"] = {"type": "json_object"}
            payload["json_schema"] = wire_schema
        elif json_mode:
            # This is an explicit, observable fallback for server builds that
            # cannot compile a particular JSON Schema into GBNF.  The caller
            # still performs full host-side Pydantic validation.
            payload["response_format"] = {"type": "json_object"}
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
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 256,
        response_schema: dict[str, Any] | None = None,
    ) -> GenerationResult:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if response_schema is not None:
            wire_schema = _inline_local_refs(response_schema)
            payload["response_format"] = {"type": "json_object"}
            payload["json_schema"] = wire_schema
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

    def _get(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(f"{self.base_url}{path}", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LlamaClientError(f"llama.cpp HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LlamaClientError(f"llama.cpp request failed: {exc}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LlamaClientError("llama.cpp returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise LlamaClientError("llama.cpp returned a non-object JSON response")
        return payload

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


def _inline_local_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Expand Pydantic's local ``$defs`` references for llama.cpp grammar.

    Pydantic's JSON Schema is excellent for API validation but commonly uses
    ``$defs``/``$ref``.  llama.cpp's schema-to-grammar path is more portable
    when it receives one self-contained schema, so only local references are
    expanded; external references remain untouched and will be rejected by
    the model boundary's normal post-response validation.
    """

    definitions = schema.get("$defs", {})

    def expand(value: Any, stack: tuple[str, ...] = ()) -> Any:
        if isinstance(value, list):
            return [expand(item, stack) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            name = reference.removeprefix("#/$defs/")
            if name in stack:
                return {"type": "object"}
            target = definitions.get(name)
            if isinstance(target, dict):
                expanded = expand(target, (*stack, name))
                siblings = {key: item for key, item in value.items() if key != "$ref"}
                if siblings and isinstance(expanded, dict):
                    expanded = {**expanded, **expand(siblings, stack)}
                return expanded
        return {
            key: expand(item, stack)
            for key, item in value.items()
            if key != "$defs"
        }

    expanded_schema = expand(schema)
    return expanded_schema if isinstance(expanded_schema, dict) else dict(schema)


def _model_ids(payload: dict[str, Any]) -> list[str]:
    entries = payload.get("data") or payload.get("models") or []
    if not isinstance(entries, list):
        return []
    return [
        str(item["id"])
        for item in entries
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
    ]
