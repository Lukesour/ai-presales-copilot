"""Dify upstream adapter for the current requirements-first v2 contracts."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .schemas import CustomerInputV2, SolutionResponseV2
from .security import wrap_untrusted_text


class DifyClientError(RuntimeError):
    """Raised when the configured Dify app cannot return a valid v2 response."""


class DifyClient:
    """Call a Dify app without exposing its API key to a browser client.

    Dify's ``/v1/chat-messages`` path is an upstream provider protocol. The
    adapter accepts only the current raw customer input and fails closed when
    the workflow does not return the public ``SolutionResponseV2`` contract.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_s: float | None = None,
    ):
        self.base_url = (base_url or os.getenv("DIFY_BASE_URL", "http://127.0.0.1")).rstrip("/")
        self.api_key = api_key or os.getenv("DIFY_APP_API_KEY", "")
        self.user = os.getenv("DIFY_USER", "portfolio-demo")
        self.timeout_s = timeout_s or float(os.getenv("DIFY_TIMEOUT_S", "60"))

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, customer_input: CustomerInputV2, *, stream: bool = False) -> SolutionResponseV2:
        if not self.configured:
            raise DifyClientError(
                "DIFY_APP_API_KEY is not configured; use the local-model FastAPI API for the demo path"
            )
        input_payload = customer_input.model_dump(mode="json")
        payload = {
            "inputs": {"customer_input": json.dumps(input_payload, ensure_ascii=False)},
            "query": wrap_untrusted_text(customer_input.raw_request),
            "response_mode": "streaming" if stream else "blocking",
            "user": self.user,
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat-messages",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.perf_counter()
        if stream:
            answer, metadata = self._stream(request)
            return self._parse_response(
                {"answer": answer, "metadata": metadata}, customer_input, started
            )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise DifyClientError(f"Dify HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise DifyClientError(f"Dify request failed: {exc}") from exc
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DifyClientError("Dify returned non-JSON output; configure v2 JSON output") from exc
        return self._parse_response(body, customer_input, started)

    def _stream(self, request: urllib.request.Request) -> tuple[str, dict[str, Any]]:
        chunks: list[str] = []
        metadata: dict[str, Any] = {}
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line.removeprefix("data:").strip())
                    except json.JSONDecodeError:
                        continue
                    chunks.append(event.get("answer", "") or "")
                    if event.get("event") == "message_end":
                        metadata.update(event.get("metadata") or {})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise DifyClientError(f"Dify streaming HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise DifyClientError(f"Dify streaming request failed: {exc}") from exc
        return "".join(chunks), metadata

    @staticmethod
    def _parse_response(
        body: dict[str, Any], customer_input: CustomerInputV2, started: float
    ) -> SolutionResponseV2:
        answer: Any = body.get("answer", body)
        if isinstance(answer, str):
            try:
                answer = json.loads(answer)
            except json.JSONDecodeError as exc:
                raise DifyClientError("Dify answer must be a JSON encoded SolutionResponseV2") from exc
        if isinstance(answer, dict) and isinstance(answer.get("response"), dict):
            answer = answer["response"]
        if not isinstance(answer, dict):
            raise DifyClientError("Dify answer must be a SolutionResponseV2 object")
        try:
            response = SolutionResponseV2.model_validate(answer)
        except ValueError as exc:
            raise DifyClientError(
                "Dify answer does not satisfy the current SolutionResponseV2 contract"
            ) from exc
        if not response.case_id or response.case_id.startswith("intake-"):
            raise DifyClientError("Dify response must contain the current run case_id")
        return response
