"""Minimal local HTTP API for demonstrating the Agent handoff contract."""

from __future__ import annotations

import json
import re
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .agent import PresalesAgent
from .schemas import CustomerBrief


class AgentHTTPHandler(BaseHTTPRequestHandler):
    """Expose health, run, checkpoint, and human-review endpoints."""

    server_version = "ai-presales-copilot/0.2"
    max_body_bytes = 1_000_000

    @property
    def service(self) -> AgentHTTPService:
        return self.server.service  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._send(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/ready":
            self._send(HTTPStatus.OK, {"status": "ready"})
            return
        match = re.fullmatch(r"/v1/runs/([^/]+)", path)
        if match:
            state = self.service.get_state(match.group(1))
            if state is None:
                self._send_error(HTTPStatus.NOT_FOUND, "run not found")
            else:
                self._send(HTTPStatus.OK, state.to_dict())
            return
        self._send_error(HTTPStatus.NOT_FOUND, "route not found")

    def do_POST(self) -> None:
        try:
            body = self._read_json()
            path = urlparse(self.path).path
            if path == "/v1/runs":
                state = self.service.start_run(body)
                self._send(HTTPStatus.OK, state.to_dict())
                return
            if path == "/v1/chat/completions":
                self._send(HTTPStatus.OK, self.service.chat_completion(body))
                return
            match = re.fullmatch(r"/v1/runs/([^/]+)/review", path)
            if match:
                state = self.service.review_run(match.group(1), body)
                self._send(HTTPStatus.OK, state.to_dict())
                return
            self._send_error(HTTPStatus.NOT_FOUND, "route not found")
        except (ValueError, TypeError) as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # noqa: BLE001  # server safety boundary
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def log_message(self, format: str, *args: object) -> None:
        # Keep demo logs short and avoid printing request bodies or credentials.
        print(f"[agent-api] {format % args}")

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > self.max_body_bytes:
            raise ValueError("request body must be between 1 byte and 1 MB")
        try:
            payload = json.loads(self.rfile.read(content_length))
        except json.JSONDecodeError as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise TypeError("request body must be a JSON object")
        return payload

    def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error(self, status: HTTPStatus, detail: str) -> None:
        self._send(status, {"error": detail})


class AgentHTTPService:
    """Application service separated from the HTTP transport for easy testing."""

    def __init__(self, agent: PresalesAgent):
        self.agent = agent

    def start_run(self, payload: dict[str, Any]):
        brief_payload = payload.get("brief", payload.get("customer_brief"))
        if not isinstance(brief_payload, dict):
            raise TypeError("brief must be a CustomerBrief JSON object")
        try:
            brief = CustomerBrief(**brief_payload)
        except TypeError as exc:
            raise ValueError(f"invalid brief: {exc}") from exc
        thread_id = payload.get("thread_id") or f"api:{brief.case_id}"
        return self.agent.run(brief, thread_id=thread_id, trace_path=payload.get("trace_path"))

    def get_state(self, thread_id: str):
        if self.agent.checkpoints is None:
            return None
        from .agent import AgentState

        payload = self.agent.checkpoints.load(thread_id)
        return AgentState.from_dict(payload) if payload else None

    def review_run(self, thread_id: str, payload: dict[str, Any]):
        decision = payload.get("decision")
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        return self.agent.run(thread_id=thread_id, review_decision=decision, trace_path=payload.get("trace_path"))

    def chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Provide a small OpenAI-compatible facade for local tools and red-team runners."""

        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a non-empty array")
        user_text = "\n".join(
            str(message.get("content", ""))
            for message in messages
            if isinstance(message, dict) and message.get("role") == "user"
        ).strip()
        if not user_text:
            raise ValueError("messages must contain user content")
        brief = CustomerBrief(
            case_id=f"chat-{uuid.uuid4().hex[:12]}",
            industry="企业",
            use_case="AI 解决方案售前分析",
            raw_request=user_text,
        )
        state = self.agent.run(brief, thread_id=f"chat:{uuid.uuid4().hex}")
        if state.response is not None:
            content = state.response.to_dict()
        else:
            content = {
                "status": state.status,
                "review_required": state.status == "pending_review",
                "risks": [risk.description for risk in state.risks],
                "run_id": state.run_id,
            }
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model", "presales-agent-offline"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(content, ensure_ascii=False),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        }


def create_server(host: str, port: int, service: AgentHTTPService) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), AgentHTTPHandler)
    server.service = service  # type: ignore[attr-defined]
    return server
