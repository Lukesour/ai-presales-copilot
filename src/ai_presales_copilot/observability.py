"""Small, dependency-free tracing primitives for the portfolio demo.

The real production choice can be Phoenix, Langfuse, or an OpenTelemetry
collector.  This module keeps the local demo inspectable without requiring a
second service and deliberately redacts common credentials and email-shaped
identifiers before a trace is written.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED]"),
    (re.compile(r"\b1[3-9]\d{9}\b"), "[PHONE_REDACTED]"),
    (re.compile(r"\b\d{17}[\dXx]\b"), "[ID_REDACTED]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL_REDACTED]"),
)


def redact(value: Any) -> Any:
    """Return a JSON-safe copy with obvious secrets removed."""

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if any(token in key.lower() for token in ("password", "secret", "token", "api_key")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        result = value
        for pattern, replacement in _SECRET_PATTERNS:
            result = pattern.sub(replacement, result)
        return result
    return value


class TraceRecorder:
    """Collect node and tool events and optionally persist them as JSONL."""

    def __init__(self, run_id: str | None = None, trace_id: str | None = None):
        self.run_id = run_id or str(uuid.uuid4())
        self.trace_id = trace_id or str(uuid.uuid4())
        self.started_at = time.perf_counter()
        self.events: list[dict[str, Any]] = []

    def record(
        self,
        event: str,
        name: str,
        *,
        status: str = "ok",
        data: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "elapsed_ms": round((time.perf_counter() - self.started_at) * 1000, 2),
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "event": event,
            "name": name,
            "status": status,
        }
        if data:
            payload["data"] = redact(data)
        if error:
            payload["error"] = redact(error)
        self.events.append(payload)

    def write_jsonl(self, path: str | Path) -> None:
        """Append one redacted event per line so resumed runs keep one trace."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            for event in self.events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
