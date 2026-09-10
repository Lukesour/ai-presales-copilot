"""FastAPI transport for the versioned local-model workflow.

The legacy ``http.server`` adapter remains in :mod:`ai_presales_copilot.api`
for the original portfolio fixtures.  This module is the Phase 0/1 API: it
uses v2 contracts, a local development token, tenant/project checks, request
ids, idempotent run/review mutations, and a single problem response shape.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

try:
    from fastapi import Request
except ImportError:  # pragma: no cover - runtime extra only
    Request = Any  # type: ignore[misc,assignment]

from .knowledge import KnowledgeBase
from .llama_client import LlamaClient, LlamaClientError
from .llm_agent import LocalModelWorkflow
from .persistence import CheckpointConflictError
from .schemas import CustomerBriefV2, StrictModel


class APIError(RuntimeError):
    """An expected API error rendered as RFC 7807-like JSON."""

    def __init__(self, status_code: int, detail: str, *, code: str = "request_error"):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code


@dataclass(frozen=True)
class AuthContext:
    tenant_id: str
    user_id: str
    roles: tuple[str, ...]
    auth_mode: str = "dev-token"


class LocalTokenAuth:
    """Small, explicit auth boundary for Compose/local development.

    Production deployments must replace this with an OIDC/JWT verifier.  A
    missing ``PRESALES_ALLOW_DEV_AUTH=true`` is deliberately a hard failure;
    the API never silently becomes an unauthenticated demo.
    """

    def __init__(self, *, token: str | None = None, allow_dev: bool | None = None):
        self.allow_dev = (
            allow_dev
            if allow_dev is not None
            else os.getenv("PRESALES_ALLOW_DEV_AUTH", "false").lower() == "true"
        )
        self.token = token or os.getenv("PRESALES_DEV_TOKEN", "dev-token")

    def authenticate(self, authorization: str | None, headers: dict[str, str]) -> AuthContext:
        if not self.allow_dev:
            raise APIError(
                503,
                "OIDC/JWT authentication is not configured; enable it explicitly for local development",
                code="auth_not_configured",
            )
        if not authorization or not authorization.lower().startswith("bearer "):
            raise APIError(401, "Authorization: Bearer <dev-token> is required", code="unauthorized")
        supplied = authorization[7:].strip()
        if not supplied or supplied != self.token:
            raise APIError(401, "invalid bearer token", code="unauthorized")
        # These headers are accepted only in explicit dev-token mode so one
        # local process can demonstrate tenant/RBAC isolation in tests.
        tenant_id = headers.get("x-tenant-id", "local")
        user_id = headers.get("x-user-id", "local-dev")
        roles = tuple(
            item.strip()
            for item in headers.get("x-roles", "admin").split(",")
            if item.strip()
        )
        allowed = {"viewer", "presales", "reviewer", "admin"}
        if not roles or any(item not in allowed for item in roles):
            raise APIError(403, "invalid role", code="forbidden")
        if not tenant_id or not user_id:
            raise APIError(400, "tenant and user headers must be non-empty", code="invalid_context")
        return AuthContext(tenant_id, user_id, roles)


class RunRequest(StrictModel):
    brief: CustomerBriefV2


class ReviewRequest(StrictModel):
    decision: str
    reason: str | None = None


class FeedbackRequest(StrictModel):
    rating: int | None = None
    label: str | None = None
    comment: str | None = None


def create_fastapi_app(
    workflow: LocalModelWorkflow,
    checkpoint_store: Any,
    knowledge_base: KnowledgeBase,
    *,
    auth: LocalTokenAuth | None = None,
    model_client: LlamaClient | None = None,
    knowledge_index: Any | None = None,
):
    """Create the Phase 1 FastAPI application.

    Imports are local so the legacy dependency-light fixtures can still import
    the package without importing Uvicorn or Starlette at module import time.
    """

    try:
        from fastapi import FastAPI
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import JSONResponse
        from pydantic import ValidationError
    except ImportError as exc:  # pragma: no cover - runtime extra only
        raise RuntimeError("Install the runtime extra to use the FastAPI service") from exc

    app = FastAPI(
        title="AI Presales Copilot API",
        version="2.0.0",
        description="Evidence-aware local-model presales workflow with human review gates.",
    )
    token_auth = auth or LocalTokenAuth()
    model = model_client or workflow.model
    rate_limit = max(1, int(os.getenv("PRESALES_RATE_LIMIT_PER_MINUTE", "60")))
    rate_window: dict[str, list[float]] = {}
    rate_lock = threading.Lock()

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or _new_request_id()
        request.state.request_id = request_id
        content_length = request.headers.get("content-length")
        try:
            content_length_value = int(content_length) if content_length else 0
        except ValueError:
            content_length_value = 1_000_001
        if content_length_value > 1_000_000:
            response = _problem(413, "request body exceeds 1 MB", "payload_too_large", request_id)
        elif request.url.path.startswith("/v1") and not _allow_request(
            request.client.host if request.client else "unknown", rate_window, rate_lock, rate_limit
        ):
            response = _problem(429, "rate limit exceeded", "rate_limited", request_id)
            response.headers["Retry-After"] = "60"
        else:
            try:
                response = await call_next(request)
            except APIError as exc:
                response = _problem(exc.status_code, exc.detail, exc.code, request_id)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        return _problem(exc.status_code, exc.detail, exc.code, request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return _problem(
            422,
            "request validation failed",
            "invalid_request",
            request.state.request_id,
            errors=exc.errors(),
        )

    @app.exception_handler(ValidationError)
    async def pydantic_error_handler(request: Request, exc: ValidationError):
        return _problem(
            422,
            "request validation failed",
            "invalid_request",
            request.state.request_id,
            errors=exc.errors(),
        )

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "service": "presales-api", "version": "2.0.0"}

    @app.get("/readyz")
    async def readyz():
        checks: dict[str, Any] = {
            "database": False,
            "knowledge_index": bool(getattr(knowledge_base, "documents", [])),
            "model": False,
        }
        if knowledge_index is not None:
            checks["pgvector"] = False
        try:
            # A read-only lookup exercises both SQLite and PostgreSQL stores.
            checkpoint_store.load_by_run_id("__readiness_probe__")
            checks["database"] = True
        except Exception as exc:  # noqa: BLE001 - readiness must report a safe summary
            checks["database_error"] = type(exc).__name__
        if knowledge_index is not None:
            try:
                checks["pgvector"] = bool(knowledge_index.health())
            except Exception as exc:  # noqa: BLE001 - readiness summary only
                checks["pgvector_error"] = type(exc).__name__
        try:
            model_status = model.health()
            checks["model"] = model_status.get("status") == 200
            if not checks["model"]:
                checks["model_error"] = f"http_{model_status.get('status')}"
        except (LlamaClientError, OSError, TimeoutError) as exc:
            checks["model_error"] = type(exc).__name__
        required_checks = ["database", "knowledge_index", "model"]
        if knowledge_index is not None:
            required_checks.append("pgvector")
        ready = all(checks[key] for key in required_checks)
        payload = {"status": "ready" if ready else "not_ready", "checks": checks}
        if not ready:
            return JSONResponse(status_code=503, content=payload)
        return payload

    @app.post("/v1/projects/{project_id}/runs")
    async def create_run(project_id: str, request: Request):
        context = _require_context(request, token_auth, {"presales", "reviewer", "admin"})
        body = await _parse_body(request)
        request_payload = RunRequest.model_validate(body)
        idempotency_key = _required_idempotency(request)
        thread_id = _idempotent_thread(context, project_id, idempotency_key)
        try:
            state = workflow.run(
                request_payload.brief,
                thread_id=thread_id,
                tenant_id=context.tenant_id,
                project_id=project_id,
                user_id=context.user_id,
                roles=list(context.roles),
                idempotency_key=idempotency_key,
            )
        except CheckpointConflictError as exc:
            raise APIError(409, str(exc), code="conflict") from exc
        except PermissionError as exc:
            raise APIError(403, str(exc), code="forbidden") from exc
        return _public_state(state)

    @app.get("/v1/runs/{run_id}")
    async def get_run(run_id: str, request: Request):
        context = _require_context(request, token_auth, {"viewer", "presales", "reviewer", "admin"})
        state = _load_authorized_state(
            checkpoint_store, run_id, context, requested_project=request.headers.get("x-project-id")
        )
        return _public_state(state)

    @app.get("/v1/runs/{run_id}/events")
    async def get_events(run_id: str, request: Request):
        context = _require_context(request, token_auth, {"viewer", "presales", "reviewer", "admin"})
        state = _load_authorized_state(
            checkpoint_store, run_id, context, requested_project=request.headers.get("x-project-id")
        )
        thread_id = str(state["thread_id"])
        return {"run_id": run_id, "events": checkpoint_store.events(thread_id)}

    @app.post("/v1/runs/{run_id}/reviews")
    async def review_run(run_id: str, request: Request):
        context = _require_context(request, token_auth, {"reviewer", "admin"})
        body = ReviewRequest.model_validate(await _parse_body(request))
        if body.decision not in {"approve", "reject"}:
            raise APIError(422, "decision must be approve or reject", code="invalid_review")
        idempotency_key = _required_idempotency(request)
        state = _load_authorized_state(
            checkpoint_store, run_id, context, requested_project=request.headers.get("x-project-id")
        )
        review = state.get("review", {})
        if review.get("idempotency_key") == idempotency_key:
            return _public_state(state)
        if state.get("status") != "waiting_for_review":
            raise APIError(409, "run is not waiting for human review", code="review_not_pending")
        try:
            updated = workflow.run(
                None,
                thread_id=state["thread_id"],
                tenant_id=context.tenant_id,
                project_id=state.get("project_id"),
                user_id=context.user_id,
                roles=list(context.roles),
                review_decision=body.decision,
                reviewer_id=context.user_id,
                reviewer_role=_reviewer_role(context.roles),
                review_reason=body.reason,
                idempotency_key=idempotency_key,
            )
        except CheckpointConflictError as exc:
            raise APIError(409, str(exc), code="conflict") from exc
        except PermissionError as exc:
            raise APIError(403, str(exc), code="forbidden") from exc
        return _public_state(updated)

    @app.post("/v1/runs/{run_id}/feedback")
    async def feedback_run(run_id: str, request: Request):
        context = _require_context(request, token_auth, {"presales", "reviewer", "admin"})
        body = FeedbackRequest.model_validate(await _parse_body(request))
        if body.rating is None and not body.label and not body.comment:
            raise APIError(422, "feedback must contain a rating, label, or comment", code="invalid_feedback")
        if body.rating is not None and not 1 <= body.rating <= 5:
            raise APIError(422, "rating must be between 1 and 5", code="invalid_feedback")
        idempotency_key = _required_idempotency(request)
        state = _load_authorized_state(
            checkpoint_store, run_id, context, requested_project=request.headers.get("x-project-id")
        )
        existing = [item for item in state.get("feedback", []) if item.get("idempotency_key") == idempotency_key]
        if existing:
            return _public_state(state)
        feedback = {
            "rating": body.rating,
            "label": body.label,
            "comment": body.comment,
            "user_id": context.user_id,
            "created_at": _utc_now(),
            "idempotency_key": idempotency_key,
        }
        state.setdefault("feedback", []).append(feedback)
        expected = int(state.get("state_version", 0))
        try:
            version = checkpoint_store.save(state["thread_id"], state, expected_version=expected)
        except CheckpointConflictError as exc:
            raise APIError(409, str(exc), code="conflict") from exc
        state["state_version"] = version
        checkpoint_store.append_event(
            state["thread_id"],
            "feedback_recorded",
            {"user_id": context.user_id, "rating": body.rating, "label": body.label},
        )
        return _public_state(state)

    @app.post("/v1/chat/completions")
    async def chat_completion(request: Request):
        context = _require_context(request, token_auth, {"presales", "reviewer", "admin"})
        body = await _parse_body(request)
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            raise APIError(422, "messages must be a non-empty array", code="invalid_request")
        user_text = "\n".join(
            str(item.get("content", ""))
            for item in messages
            if isinstance(item, dict) and item.get("role") == "user"
        ).strip()
        if not user_text:
            raise APIError(422, "messages must contain user content", code="invalid_request")
        idempotency_key = _required_idempotency(request)
        project_id = request.headers.get("x-project-id", "default")
        brief = CustomerBriefV2(
            case_id=f"chat-{hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]}",
            industry="企业",
            use_case="AI 解决方案售前分析",
            raw_request=user_text,
        )
        try:
            state = workflow.run(
                brief,
                thread_id=_idempotent_thread(context, project_id, idempotency_key),
                tenant_id=context.tenant_id,
                project_id=project_id,
                user_id=context.user_id,
                roles=list(context.roles),
                idempotency_key=idempotency_key,
            )
        except CheckpointConflictError as exc:
            raise APIError(409, str(exc), code="conflict") from exc
        except PermissionError as exc:
            raise APIError(403, str(exc), code="forbidden") from exc
        public = _public_state(state)
        content = public.get("response") or {
            "schema_version": "2.0",
            "status": state.get("status"),
            "run_id": state.get("run_id"),
            "error_code": state.get("error_code"),
            "risks": state.get("risks", []),
        }
        return {
            "id": f"chatcmpl-{state['run_id']}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", model.model),
            "run_id": state["run_id"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": json.dumps(content, ensure_ascii=False)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        }

    return app


async def _parse_body(request: Any) -> dict[str, Any]:
    try:
        raw = await request.body()
    except Exception as exc:
        raise APIError(400, "request body could not be read", code="invalid_request") from exc
    if len(raw) > 1_000_000:
        raise APIError(413, "request body exceeds 1 MB", code="payload_too_large")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise APIError(400, "request body must be valid JSON", code="invalid_json") from exc
    if not isinstance(body, dict):
        raise APIError(422, "request body must be a JSON object", code="invalid_request")
    return body


def _require_context(request: Any, auth: LocalTokenAuth, allowed_roles: set[str]) -> AuthContext:
    context = auth.authenticate(
        request.headers.get("authorization"),
        {key.lower(): value for key, value in request.headers.items()},
    )
    if not allowed_roles.intersection(context.roles):
        raise APIError(403, "insufficient role", code="forbidden")
    return context


def _load_authorized_state(
    store: Any,
    run_id: str,
    context: AuthContext,
    *,
    requested_project: str | None = None,
) -> dict[str, Any]:
    state = store.load_by_run_id(run_id)
    if state is None:
        raise APIError(404, "run not found", code="not_found")
    if state.get("tenant_id", "local") != context.tenant_id:
        raise APIError(404, "run not found", code="not_found")
    # Reviewers may read all projects in their tenant; viewers/presales still
    # need the explicit project header for cross-project reads.
    if (
        state.get("project_id")
        and context.roles
        and not ({"admin", "reviewer"} & set(context.roles))
        and requested_project != state.get("project_id")
    ):
        raise APIError(404, "run not found", code="not_found")
    if state.get("user_id") not in {None, context.user_id} and not ({"reviewer", "admin"} & set(context.roles)):
        raise APIError(404, "run not found", code="not_found")
    return state


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "run_id": state.get("run_id"),
        "trace_id": state.get("trace_id"),
        "thread_id": state.get("thread_id"),
        "tenant_id": state.get("tenant_id"),
        "project_id": state.get("project_id"),
        "status": state.get("status"),
        "current_node": state.get("current_node"),
        "state_version": state.get("state_version", 0),
        "response": state.get("response"),
        "review": state.get("review"),
        "errors": state.get("errors", []),
        "error_code": state.get("error_code"),
        "feedback": state.get("feedback", []),
        "created_at": state.get("created_at"),
    }


def _required_idempotency(request: Any) -> str:
    value = request.headers.get("idempotency-key", "").strip()
    if not value:
        raise APIError(400, "Idempotency-Key header is required", code="idempotency_required")
    if len(value) > 256:
        raise APIError(400, "Idempotency-Key is too long", code="invalid_idempotency_key")
    return value


def _allow_request(
    key: str,
    windows: dict[str, list[float]],
    lock: threading.Lock,
    limit: int,
) -> bool:
    now = time.monotonic()
    with lock:
        values = [item for item in windows.get(key, []) if now - item < 60]
        if len(values) >= limit:
            windows[key] = values
            return False
        values.append(now)
        windows[key] = values
        return True


def _idempotent_thread(context: AuthContext, project_id: str, key: str) -> str:
    raw = f"{context.tenant_id}\x00{context.user_id}\x00{project_id}\x00{key}"
    return "api:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _reviewer_role(roles: tuple[str, ...]) -> str:
    return "admin" if "admin" in roles else "reviewer"


def _new_request_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _problem(
    status_code: int,
    detail: str,
    code: str,
    request_id: str,
    *,
    errors: list[Any] | None = None,
):
    from fastapi.responses import JSONResponse

    payload: dict[str, Any] = {
        "type": f"https://ai-presales-copilot.local/problems/{code}",
        "title": code,
        "status": status_code,
        "detail": detail,
        "request_id": request_id,
    }
    if errors is not None:
        payload["errors"] = errors
    return JSONResponse(status_code=status_code, content=payload)
