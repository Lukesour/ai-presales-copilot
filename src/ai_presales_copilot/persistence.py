"""Durable run checkpoints, audit events, and native LangGraph persistence."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

CHECKPOINT_FORMAT = "requirements-first-v2"
CHECKPOINT_FORMAT_VERSION = 1


class CheckpointConflictError(RuntimeError):
    """Raised when a stale reviewer tries to overwrite a newer state."""


class CheckpointFormatError(RuntimeError):
    """Raised when persisted state does not match the current checkpoint format."""


class CheckpointStore:
    """Persist the latest JSON-serializable state for each Agent thread."""

    def __init__(self, path: str | Path = ".runtime/agent/checkpoints.db"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.RLock()
        self.connection.execute("PRAGMA busy_timeout = 5000")
        if self.path != ":memory:":
            self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_checkpoints (
                thread_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                state_version INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        columns = {
            row[1]
            for row in self.connection.execute("PRAGMA table_info(agent_checkpoints)").fetchall()
        }
        if "state_version" not in columns:
            self.connection.execute(
                "ALTER TABLE agent_checkpoints ADD COLUMN state_version INTEGER NOT NULL DEFAULT 0"
            )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def save(
        self,
        thread_id: str,
        state: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> int:
        with self._lock:
            row = self.connection.execute(
                "SELECT state_version FROM agent_checkpoints WHERE thread_id = ?", (thread_id,)
            ).fetchone()
            current_version = int(row[0]) if row else 0
            if expected_version is not None and current_version != expected_version:
                raise CheckpointConflictError(
                    f"checkpoint version conflict for {thread_id}: "
                    f"expected {expected_version}, current {current_version}"
                )
            next_version = current_version + 1
            persisted_state = dict(state)
            persisted_state["state_version"] = next_version
            persisted_state["state_format"] = CHECKPOINT_FORMAT
            persisted_state["state_format_version"] = CHECKPOINT_FORMAT_VERSION
            self.connection.execute(
                """
                INSERT INTO agent_checkpoints(thread_id, state_json, updated_at, state_version)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at,
                    state_version=excluded.state_version
                """,
                (
                    thread_id,
                    json.dumps(persisted_state, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                    next_version,
                ),
            )
            self.connection.commit()
            return next_version

    def load(self, thread_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT state_json FROM agent_checkpoints WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        if row is None:
            return None
        return _validate_checkpoint_payload(json.loads(row[0]))

    def load_by_run_id(self, run_id: str) -> dict[str, Any] | None:
        """Find a checkpoint by its public run id.

        SQLite JSON1 is not required for the portfolio runtime, so this uses a
        small bounded scan instead of assuming a particular SQLite build.  A
        production deployment should add a generated/indexed run_id column.
        """

        with self._lock:
            rows = self.connection.execute(
                "SELECT state_json FROM agent_checkpoints ORDER BY updated_at DESC"
            ).fetchall()
        for (payload,) in rows:
            state = _validate_checkpoint_payload(json.loads(payload))
            if state.get("run_id") == run_id:
                return state
        return None

    def thread_for_run_id(self, run_id: str) -> str | None:
        state = self.load_by_run_id(run_id)
        return str(state["thread_id"]) if state and state.get("thread_id") else None

    def append_event(self, thread_id: str, event_type: str, event: dict[str, Any]) -> None:
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO agent_events(thread_id, event_type, event_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    thread_id,
                    event_type,
                    json.dumps(event, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )
            self.connection.commit()

    def events(self, thread_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT event_type, event_json, created_at FROM agent_events "
                "WHERE thread_id = ? ORDER BY event_id",
                (thread_id,),
            ).fetchall()
        return [
            {"event_type": event_type, "created_at": created_at, **json.loads(payload)}
            for event_type, payload, created_at in rows
        ]

    def delete(self, thread_id: str) -> None:
        with self._lock:
            self.connection.execute("DELETE FROM agent_checkpoints WHERE thread_id = ?", (thread_id,))
            self.connection.commit()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class PostgresCheckpointStore:
    """PostgreSQL checkpoint/audit store for the Compose runtime.

    The dependency is imported lazily so the dependency-free unit fixtures can
    continue to use SQLite.  The schema intentionally mirrors the SQLite
    store, which keeps the Agent state contract portable between demo and
    container deployments.
    """

    def __init__(self, dsn: str):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - runtime extra only
            raise RuntimeError("Install the runtime extra to use PostgreSQL checkpoints") from exc
        self.connection = psycopg.connect(dsn, autocommit=True, connect_timeout=10)
        self._lock = threading.RLock()
        self.native_graph_checkpointer = None
        self._native_graph_connection = None
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_checkpoints (
                    thread_id TEXT PRIMARY KEY,
                    state_json JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    state_version INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_events (
                    event_id BIGSERIAL PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )

        # Keep the application checkpoint for run-level optimistic locking and
        # audit queries, while also projecting graph state into the native
        # LangGraph saver for interrupt/resume semantics.  Separate psycopg
        # connections avoid sharing cursors across the two protocols.
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row

            self._native_graph_connection = psycopg.connect(
                dsn,
                autocommit=True,
                connect_timeout=10,
                prepare_threshold=0,
                row_factory=dict_row,
            )
            self.native_graph_checkpointer = PostgresSaver(self._native_graph_connection)
            self.native_graph_checkpointer.setup()
        except ImportError:
            # The native saver is optional for the SQLite/dependency-light path.
            self.native_graph_checkpointer = None

    def save(
        self,
        thread_id: str,
        state: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> int:
        # The connection is autocommit for LangGraph's PostgresSaver, so the
        # version read and write must explicitly share one transaction.  A
        # standalone SELECT ... FOR UPDATE would otherwise release its lock
        # before the INSERT/UPDATE and allow two reviewers to pass the same
        # optimistic-lock check.
        with self._lock, self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT state_version FROM agent_checkpoints WHERE thread_id = %s FOR UPDATE",
                (thread_id,),
            )
            row = cursor.fetchone()
            current_version = int(row[0]) if row else 0
            if expected_version is not None and current_version != expected_version:
                raise CheckpointConflictError(
                    f"checkpoint version conflict for {thread_id}: "
                    f"expected {expected_version}, current {current_version}"
                )
            next_version = current_version + 1
            persisted_state = dict(state)
            persisted_state["state_version"] = next_version
            persisted_state["state_format"] = CHECKPOINT_FORMAT
            persisted_state["state_format_version"] = CHECKPOINT_FORMAT_VERSION
            cursor.execute(
                """
                INSERT INTO agent_checkpoints(thread_id, state_json, updated_at, state_version)
                VALUES (%s, %s::jsonb, now(), %s)
                ON CONFLICT(thread_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at,
                    state_version=excluded.state_version
                """,
                (thread_id, json.dumps(persisted_state, ensure_ascii=False), next_version),
            )
            return next_version

    def load(self, thread_id: str) -> dict[str, Any] | None:
        with self._lock, self.connection.cursor() as cursor:
            cursor.execute("SELECT state_json FROM agent_checkpoints WHERE thread_id = %s", (thread_id,))
            row = cursor.fetchone()
        return _validate_checkpoint_payload(dict(row[0])) if row else None

    def load_by_run_id(self, run_id: str) -> dict[str, Any] | None:
        with self._lock, self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT state_json FROM agent_checkpoints WHERE state_json->>'run_id' = %s",
                (run_id,),
            )
            row = cursor.fetchone()
        return _validate_checkpoint_payload(dict(row[0])) if row else None

    def thread_for_run_id(self, run_id: str) -> str | None:
        state = self.load_by_run_id(run_id)
        return str(state["thread_id"]) if state and state.get("thread_id") else None

    def append_event(self, thread_id: str, event_type: str, event: dict[str, Any]) -> None:
        with self._lock, self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO agent_events(thread_id, event_type, event_json, created_at) "
                "VALUES (%s, %s, %s::jsonb, now())",
                (thread_id, event_type, json.dumps(event, ensure_ascii=False)),
            )

    def events(self, thread_id: str) -> list[dict[str, Any]]:
        with self._lock, self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT event_type, event_json, created_at FROM agent_events "
                "WHERE thread_id = %s ORDER BY event_id",
                (thread_id,),
            )
            rows = cursor.fetchall()
        return [
            {"event_type": event_type, "created_at": created_at.isoformat(), **dict(payload)}
            for event_type, payload, created_at in rows
        ]

    def delete(self, thread_id: str) -> None:
        with self._lock, self.connection.transaction(), self.connection.cursor() as cursor:
            cursor.execute("DELETE FROM agent_events WHERE thread_id = %s", (thread_id,))
            cursor.execute("DELETE FROM agent_checkpoints WHERE thread_id = %s", (thread_id,))

    def close(self) -> None:
        with self._lock:
            if self._native_graph_connection is not None:
                self._native_graph_connection.close()
            self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def create_checkpoint_store(location: str | Path):
    """Create SQLite or PostgreSQL storage from a path/DSN."""

    value = str(location)
    if value.startswith(("postgres://", "postgresql://")):
        return PostgresCheckpointStore(value)
    return CheckpointStore(value)


def _validate_checkpoint_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CheckpointFormatError("checkpoint payload is not an object; local clean reset is required")
    if payload.get("state_format") != CHECKPOINT_FORMAT:
        raise CheckpointFormatError(
            "checkpoint format is unsupported or missing; old state is not converted, "
            "and an authorized local clean reset is required"
        )
    if payload.get("state_format_version") != CHECKPOINT_FORMAT_VERSION:
        raise CheckpointFormatError(
            "checkpoint format version is unsupported; create a new local checkpoint store "
            "after confirming the old data can be retained"
        )
    return payload
