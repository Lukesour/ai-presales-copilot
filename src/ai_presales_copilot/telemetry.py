"""Optional OpenTelemetry bridge with a safe no-op default.

The service records redacted JSONL events regardless of exporter setup. When
the runtime extra is installed, the same run/node/model boundaries become OTel
spans; raw prompts and retrieved text are intentionally never span attributes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover - dependency-light fixtures
        yield None
        return
    tracer = trace.get_tracer("ai-presales-copilot")
    with tracer.start_as_current_span(name) as current:
        for key, value in (attributes or {}).items():
            if value is not None:
                current.set_attribute(key, value)
        yield current
