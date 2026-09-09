"""Minimal Dify App API adapter with timeouts and safe error messages."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .schemas import CustomerBrief, SolutionResponse, validate_solution_dict
from .security import wrap_untrusted_text


class DifyClientError(RuntimeError):
    """Raised when the configured Dify app cannot return a usable response."""


class DifyClient:
    """Call a Dify app without exposing the API key to a browser client."""

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

    def chat(self, brief: CustomerBrief, *, stream: bool = False) -> SolutionResponse:
        if not self.configured:
            raise DifyClientError(
                "DIFY_APP_API_KEY is not configured; use --mode mock for offline demo"
            )
        payload = {
            "inputs": {"customer_brief": json.dumps(brief.to_dict(), ensure_ascii=False)},
            "query": wrap_untrusted_text(brief.raw_request or brief.use_case),
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
            response = self._to_solution({"answer": answer, "metadata": metadata}, brief)
            response.latency_ms = round((time.perf_counter() - started) * 1000, 2)
            return response
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
            raise DifyClientError(
                "Dify returned non-JSON output; configure blocking response mode"
            ) from exc
        response = self._to_solution(body, brief)
        response.latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return response

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
    def _to_solution(body: dict[str, Any], brief: CustomerBrief) -> SolutionResponse:
        """Accept a structured Dify JSON answer or preserve raw text for inspection."""

        answer = body.get("answer", body)
        if isinstance(answer, str):
            try:
                answer = json.loads(answer)
            except json.JSONDecodeError:
                return SolutionResponse(
                    case_id=brief.case_id,
                    executive_summary=answer,
                    model_name="dify",
                    usage=body.get("metadata", {}).get("usage", {}),
                )
        if not isinstance(answer, dict):
            raise DifyClientError("Dify answer must be a JSON object or JSON string")
        answer.setdefault("case_id", brief.case_id)
        validate_solution_dict(answer)
        answer["model_name"] = "dify"
        answer["usage"] = body.get("metadata", {}).get("usage", {})
        return _solution_from_dict(answer)


def _solution_from_dict(payload: dict[str, Any]) -> SolutionResponse:
    from .schemas import Evidence, Requirement, RiskFlag

    return SolutionResponse(
        case_id=payload["case_id"],
        executive_summary=payload["executive_summary"],
        requirements=[Requirement(**item) for item in payload.get("requirements", [])],
        recommendation=payload.get("recommendation", []),
        architecture=payload.get("architecture", []),
        implementation_steps=payload.get("implementation_steps", []),
        risks=[RiskFlag(**item) for item in payload.get("risks", [])],
        clarifying_questions=payload.get("clarifying_questions", []),
        evidence=[Evidence(**item) for item in payload.get("evidence", [])],
        poc_plan=payload.get("poc_plan", []),
        model_strategy=payload.get("model_strategy", {}),
        assumptions=payload.get("assumptions", []),
        review_status=payload.get("review_status", "not_required"),
        model_name=payload.get("model_name", "dify"),
        latency_ms=payload.get("latency_ms"),
        usage=payload.get("usage", {}),
        run_id=payload.get("run_id"),
        trace_id=payload.get("trace_id"),
    )
