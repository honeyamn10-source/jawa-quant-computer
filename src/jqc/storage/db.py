"""SQLite storage with an idempotent migration runner.

WAL mode is enabled so the API and background jobs can read/write
concurrently. ``check_same_thread=False`` lets a connection be shared by
asyncio workers; writes are serialized with a global lock.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

MIGRATIONS: list[tuple[str, str]] = [
    (
        "001_initial",
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL DEFAULT 'default',
            title TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            task_id TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            workspace TEXT NOT NULL DEFAULT 'default',
            request TEXT NOT NULL,
            status TEXT NOT NULL,
            plan_json TEXT,
            result TEXT,
            error TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            started_at REAL,
            finished_at REAL
        );
        CREATE TABLE IF NOT EXISTS task_steps (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            step_index INTEGER NOT NULL,
            tool TEXT NOT NULL,
            action TEXT NOT NULL,
            params_json TEXT NOT NULL,
            status TEXT NOT NULL,
            evidence_json TEXT,
            error TEXT,
            created_at REAL NOT NULL,
            finished_at REAL
        );
        CREATE TABLE IF NOT EXISTS event_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            tool TEXT,
            action TEXT,
            message TEXT,
            evidence_json TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS providers (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            base_url TEXT,
            model TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            is_default INTEGER NOT NULL DEFAULT 0,
            config_json TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scheduled_jobs (
            id TEXT PRIMARY KEY,
            workspace TEXT NOT NULL DEFAULT 'default',
            name TEXT NOT NULL,
            prompt TEXT NOT NULL,
            schedule_type TEXT NOT NULL,          -- once | interval | cron
            trigger_json TEXT NOT NULL,           -- {at|every|cron_string|tz}
            enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'idle',  -- idle | running | completed | failed | cancelled
            last_run_at REAL,
            next_run_at REAL,
            last_result TEXT,
            retry_policy_json TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            step_id TEXT,
            skill TEXT,
            action TEXT,
            resource TEXT,
            status TEXT NOT NULL,
            approval TEXT,
            outcome TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            risk TEXT NOT NULL,
            pattern TEXT NOT NULL,
            policy TEXT NOT NULL,   -- ask | allow | deny
            scope TEXT NOT NULL DEFAULT 'task',
            note TEXT,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY,
            task_id TEXT,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            resource TEXT,
            risk TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            decided_at REAL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,                    -- task | preference | workspace | semantic
            scope TEXT NOT NULL DEFAULT 'default',
            key TEXT,
            content TEXT NOT NULL,
            metadata_json TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS indexed_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace TEXT NOT NULL DEFAULT 'default',
            path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            metadata_json TEXT,
            embedding BLOB,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS kv (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_steps_task ON task_steps(task_id);
        CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_events(created_at);
        CREATE INDEX IF NOT EXISTS idx_jobs_enabled ON scheduled_jobs(enabled, next_run_at);
        CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);
        """,
    ),
]


class Database:
    """Minimal thread-safe SQLite wrapper."""

    def __init__(self, path: Path, migrate: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        if migrate:
            self.migrate()

    def migrate(self) -> None:
        with self._lock:
            row = self._conn.execute("SELECT user_version FROM pragma_user_version").fetchone()
            version = int(row[0]) if row else 0
            for i, (_name, sql) in enumerate(MIGRATIONS, start=1):
                if i <= version:
                    continue
                self._conn.executescript(sql)
                self._conn.execute(f"PRAGMA user_version={i}")
            self._conn.commit()

    def _query(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def executescript(self, sql: str) -> None:
        with self._lock:
            self._conn.executescript(sql)
            self._conn.commit()

    def cursor(self) -> sqlite3.Cursor:
        """Raw cursor for callers that must iterate; lock ownership is the caller's."""
        return self._conn.cursor()

    def rows(self, sql: str, params: tuple = ()) -> list[dict]:
        """Execute a SELECT and return a list of plain dicts."""
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params)]

    def fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
