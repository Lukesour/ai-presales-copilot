"""SQLite checkpoint storage for resumable Agent runs."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self


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
                updated_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def save(self, thread_id: str, state: dict[str, Any]) -> None:
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO agent_checkpoints(thread_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (
                    thread_id,
                    json.dumps(state, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )
            self.connection.commit()

    def load(self, thread_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT state_json FROM agent_checkpoints WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

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
