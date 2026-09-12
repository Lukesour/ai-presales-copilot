"""FastAPI transport for the requirements-first v2 workflow.

The service owns only the current public ``/v2`` contract. External provider
protocols such as a llama-server OpenAI-compatible ``/v1`` endpoint are kept
behind their client boundaries and are not project routes.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field

try:
    from fastapi import Request
except ImportError:  # pragma: no cover - runtime extra only
    Request = Any  # type: ignore[misc,assignment]

from .knowledge import KnowledgeBase
from .llama_client import LlamaClient, LlamaClientError
from .llm_agent import LocalModelWorkflow
from .persistence import CheckpointConflictError, CheckpointFormatError
from .schemas import (
    ClarificationRequestV2,
    CustomerInputV2,
    RequirementConfirmRequestV2,
    RunInputRequestV2,
    StrictModel,
)


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


class V2ReviewRequest(StrictModel):
    """Review mutation with mandatory optimistic concurrency control."""

    decision: Literal["approve", "reject"]
    reason: str | None = None
    state_version: int = Field(..., ge=0)


class V2FeedbackRequest(StrictModel):
    """Feedback mutation with mandatory optimistic concurrency control."""

    rating: int | None = Field(default=None, ge=1, le=5)
    label: str | None = None
    comment: str | None = None
    state_version: int = Field(..., ge=0)


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

    Imports are local so dependency-light tooling can import the package
    without importing Uvicorn or Starlette at module import time.
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
        elif request.url.path.startswith("/v2") and not _allow_request(
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
    def readyz():
        knowledge_loaded = bool(getattr(knowledge_base, "documents", []))
        if knowledge_index is not None and not knowledge_loaded:
            try:
                knowledge_loaded = bool(knowledge_index.has_sources())
            except Exception:  # noqa: BLE001 - the dedicated pgvector check below reports details
                knowledge_loaded = False
        checks: dict[str, Any] = {
            "database": False,
            "knowledge_index": knowledge_loaded,
            "model": False,
        }
        if knowledge_index is not None:
            checks["pgvector"] = False
        try:
            check_store = getattr(checkpoint_store, "check_readiness", None)
            if callable(check_store):
                check_store()
            else:
                # Keep compatibility with a narrow test double that only
                # exposes the historical read-only lookup seam.
                checkpoint_store.load_by_run_id("__readiness_probe__")
            checks["database"] = True
        except CheckpointFormatError as exc:
            checks.update(
                {
                    "database_error": type(exc).__name__,
                    "database_error_code": "checkpoint_format_unsupported",
                    "database_error_detail": str(exc),
                    "database_action": (
                        "Retain the old store and start with a new current-format store, "
                        "or run an explicitly authorized migration."
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 - readiness must report a safe summary
            checks.update(
                {
                    "database_error": type(exc).__name__,
                    "database_error_code": "database_unavailable",
                }
            )
        if knowledge_index is not None:
            try:
                checks["pgvector"] = bool(knowledge_index.health())
            except Exception as exc:  # noqa: BLE001 - readiness summary only
                checks["pgvector_error"] = type(exc).__name__
        try:
            model_readiness = getattr(model, "readiness", None)
            model_status = (
                model_readiness()
                if callable(model_readiness)
                else model.health()
            )
            if callable(model_readiness):
                checks["model"] = model_status.get("status") == "ready"
                if not checks["model"]:
                    checks["model_error_code"] = model_status.get(
                        "error_code", "model_unavailable"
                    )
                    if model_status.get("detail"):
                        checks["model_error_detail"] = model_status["detail"]
                    if model_status.get("configured_model"):
                        checks["model_configured"] = model_status["configured_model"]
                    if model_status.get("available_models"):
                        checks["model_available"] = model_status["available_models"]
            else:
                checks["model"] = model_status.get("status") == 200
            if not checks["model"]:
                checks.setdefault(
                    "model_error",
                    model_status.get("error_code", f"http_{model_status.get('status')}"),
                )
        except (LlamaClientError, OSError, TimeoutError) as exc:
            checks.update(
                {
                    "model_error": type(exc).__name__,
                    "model_error_code": "model_unavailable",
                }
            )
        required_checks = ["database", "knowledge_index", "model"]
        if knowledge_index is not None:
            required_checks.append("pgvector")
        ready = all(checks[key] for key in required_checks)
        payload = {"status": "ready" if ready else "not_ready", "checks": checks}
        if not ready:
            return JSONResponse(status_code=503, content=payload)
        return payload

    # ------------------------------------------------------------------
    # Requirements-first v2 transport.
    # ------------------------------------------------------------------

    @app.post("/v2/projects/{project_id}/runs")
    async def create_input_run(project_id: str, request: Request):
        context = _require_context(request, token_auth, {"presales", "reviewer", "admin"})
        payload = RunInputRequestV2.model_validate(await _parse_body(request))
        idempotency_key = _required_idempotency(request)
        input_payload = payload.input
        if payload.source is not None:
            input_payload = input_payload.model_copy(update={"source": payload.source})
        thread_id = _idempotent_thread(context, project_id, idempotency_key)
        try:
            state = workflow.start_input(
                input_payload,
                thread_id=thread_id,
                tenant_id=context.tenant_id,
                project_id=project_id,
                user_id=context.user_id,
                roles=list(context.roles),
                idempotency_key=idempotency_key,
            )
        except CheckpointConflictError as exc:
            raise APIError(409, str(exc), code="conflict") from exc
        except CheckpointFormatError as exc:
            raise APIError(409, str(exc), code="checkpoint_format_unsupported") from exc
        except PermissionError as exc:
            raise APIError(403, str(exc), code="forbidden") from exc
        return _public_state(state)

    @app.get("/v2/runs/{run_id}")
    async def get_input_run(run_id: str, request: Request):
        context = _require_context(request, token_auth, {"viewer", "presales", "reviewer", "admin"})
        state = _load_authorized_state(
            checkpoint_store, run_id, context, requested_project=request.headers.get("x-project-id")
        )
        return _public_state(state)

    @app.get("/v2/runs/{run_id}/events")
    async def get_input_events(run_id: str, request: Request):
        context = _require_context(request, token_auth, {"viewer", "presales", "reviewer", "admin"})
        state = _load_authorized_state(
            checkpoint_store, run_id, context, requested_project=request.headers.get("x-project-id")
        )
        return {"run_id": run_id, "events": checkpoint_store.events(str(state["thread_id"]))}

    @app.post("/v2/runs/{run_id}/clarifications")
    async def clarify_input_run(run_id: str, request: Request):
        context = _require_context(request, token_auth, {"presales", "reviewer", "admin"})
        body = ClarificationRequestV2.model_validate(await _parse_body(request))
        idempotency_key = _required_idempotency(request)
        expected_state_version = (
            body.expected_state_version
            if body.expected_state_version is not None
            else body.state_version
        )
        if expected_state_version is None:
            raise APIError(400, "state_version is required", code="state_version_required")
        state = _load_authorized_state(
            checkpoint_store, run_id, context, requested_project=request.headers.get("x-project-id")
        )
        try:
            updated = workflow.add_clarification(
                thread_id=str(state["thread_id"]),
                message=body.message,
                overrides=body.overrides,
                expected_state_version=expected_state_version,
                idempotency_key=idempotency_key,
                tenant_id=context.tenant_id,
                project_id=state.get("project_id"),
                user_id=context.user_id,
                roles=list(context.roles),
            )
        except CheckpointConflictError as exc:
            raise APIError(409, str(exc), code="conflict") from exc
        except PermissionError as exc:
            raise APIError(403, str(exc), code="forbidden") from exc
        except ValueError as exc:
            raise APIError(422, str(exc), code="invalid_clarification") from exc
        return _public_state(updated)

    @app.post("/v2/runs/{run_id}/requirements/confirm")
    async def confirm_input_requirements(run_id: str, request: Request):
        context = _require_context(request, token_auth, {"presales", "reviewer", "admin"})
        body = RequirementConfirmRequestV2.model_validate(await _parse_body(request))
        idempotency_key = _required_idempotency(request)
        expected_state_version = (
            body.expected_state_version
            if body.expected_state_version is not None
            else body.state_version
        )
        if expected_state_version is None:
            raise APIError(400, "state_version is required", code="state_version_required")
        state = _load_authorized_state(
            checkpoint_store, run_id, context, requested_project=request.headers.get("x-project-id")
        )
        try:
            updated = workflow.confirm_requirements(
                thread_id=str(state["thread_id"]),
                acknowledged_warnings=body.acknowledged_warnings,
                expected_state_version=expected_state_version,
                idempotency_key=idempotency_key,
                tenant_id=context.tenant_id,
                project_id=state.get("project_id"),
                user_id=context.user_id,
                roles=list(context.roles),
            )
        except CheckpointConflictError as exc:
            raise APIError(409, str(exc), code="conflict") from exc
        except PermissionError as exc:
            raise APIError(403, str(exc), code="forbidden") from exc
        except ValueError as exc:
            raise APIError(422, str(exc), code="requirements_not_confirmable") from exc
        return _public_state(updated)

    @app.post("/v2/runs/{run_id}/reviews")
    async def review_input_run(run_id: str, request: Request):
        context = _require_context(request, token_auth, {"reviewer", "admin"})
        body = V2ReviewRequest.model_validate(await _parse_body(request))
        if body.decision not in {"approve", "reject"}:
            raise APIError(422, "decision must be approve or reject", code="invalid_review")
        idempotency_key = _required_idempotency(request)
        state = _load_authorized_state(
            checkpoint_store, run_id, context, requested_project=request.headers.get("x-project-id")
        )
        if body.state_version != int(state.get("state_version", 0)):
            raise APIError(409, "state version conflict", code="conflict")
        if state.get("status") != "waiting_for_review":
            raise APIError(409, "run is not waiting for human review", code="review_not_pending")
        if state.get("review", {}).get("idempotency_key") == idempotency_key:
            return _public_state(state)
        try:
            updated = workflow.run(
                None,
                thread_id=str(state["thread_id"]),
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

    @app.post("/v2/runs/{run_id}/feedback")
    async def feedback_input_run(run_id: str, request: Request):
        context = _require_context(request, token_auth, {"presales", "reviewer", "admin"})
        body = V2FeedbackRequest.model_validate(await _parse_body(request))
        if body.rating is None and not body.label and not body.comment:
            raise APIError(422, "feedback must contain a rating, label, or comment", code="invalid_feedback")
        if body.rating is not None and not 1 <= body.rating <= 5:
            raise APIError(422, "rating must be between 1 and 5", code="invalid_feedback")
        idempotency_key = _required_idempotency(request)
        state = _load_authorized_state(
            checkpoint_store, run_id, context, requested_project=request.headers.get("x-project-id")
        )
        if body.state_version != int(state.get("state_version", 0)):
            raise APIError(409, "state version conflict", code="conflict")
        if any(item.get("idempotency_key") == idempotency_key for item in state.get("feedback", [])):
            return _public_state(state)
        state.setdefault("feedback", []).append(
            {
                "rating": body.rating,
                "label": body.label,
                "comment": body.comment,
                "user_id": context.user_id,
                "created_at": _utc_now(),
                "idempotency_key": idempotency_key,
            }
        )
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

    @app.post("/v2/chat/completions")
    async def requirements_chat_completion(request: Request):
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
        try:
            state = workflow.start_input(
                CustomerInputV2(raw_request=user_text, source="chat"),
                thread_id=_idempotent_thread(context, project_id, idempotency_key),
                tenant_id=context.tenant_id,
                project_id=project_id,
                user_id=context.user_id,
                roles=list(context.roles),
                idempotency_key=idempotency_key,
            )
        except CheckpointConflictError as exc:
            raise APIError(409, str(exc), code="conflict") from exc
        except CheckpointFormatError as exc:
            raise APIError(409, str(exc), code="checkpoint_format_unsupported") from exc
        public = _public_state(state)
        return {
            "id": f"chatcmpl-{state['run_id']}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", model.model),
            "run_id": state["run_id"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": json.dumps(public, ensure_ascii=False)},
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
    try:
        state = store.load_by_run_id(run_id)
    except CheckpointFormatError as exc:
        raise APIError(409, str(exc), code="checkpoint_format_unsupported") from exc
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
        "phase": state.get("phase", "solution" if state.get("response") else "requirements"),
        "status": state.get("status"),
        "current_node": state.get("current_node"),
        "state_version": state.get("state_version", 0),
        "input": state.get("input"),
        "input_turns": state.get("input_turns", []),
        "brief": state.get("intake_brief", state.get("brief", {})),
        "requirement_facts": state.get("requirement_facts", []),
        "requirement_conflicts": state.get("requirement_conflicts", []),
        "requirement_analysis": state.get("requirement_analysis", {}),
        "requirements_confirmed": bool(state.get("requirements_confirmed", False)),
        "extraction_mode": state.get("extraction_mode", "model"),
        "structured_schema_fallbacks": state.get("structured_schema_fallbacks", []),
        "response": state.get("response"),
        # Keep only the deterministic missing-field projection public; prompts,
        # policy matches, and other internal workflow state stay server-owned.
        "clarify": state.get("clarify", {"missing_fields": [], "questions": []}),
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
