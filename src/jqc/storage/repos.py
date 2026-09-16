"""Repository helpers over :class:`jqc.storage.db.Database`."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from jqc.core.schemas import Event, TaskStatus
from jqc.storage.db import Database

HIDDEN_FIELDS = {"evidence_json", "params_json", "config_json", "trigger_json", "metadata_json"}


def _now() -> float:
    return time.time()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}" if prefix else uuid.uuid4().hex


def rows_to_dicts(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        for k in HIDDEN_FIELDS:
            if k in d and d[k] is not None:
                d[k.rstrip("_json")] = json.loads(d.pop(k))
        out.append(d)
    return out


class Tasks:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, workspace: str, request: str, conversation_id: str | None) -> str:
        tid = new_id("t_")
        now = _now()
        self.db.execute(
            "INSERT INTO tasks (id, conversation_id, workspace, request, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (tid, conversation_id, workspace, request, TaskStatus.queued.value, now, now),
        )
        return tid

    def get(self, task_id: str) -> dict | None:
        row = self.db.fetchone("SELECT * FROM tasks WHERE id=?", (task_id,))
        return rows_to_dicts([row])[0] if row else None

    def update(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        params = list(fields.values()) + [_now(), task_id]
        self.db.execute(f"UPDATE tasks SET {cols}, updated_at=? WHERE id=?", tuple(params))

    def set_status(self, task_id: str, status: TaskStatus | str) -> None:
        self.update(task_id, status=status if isinstance(status, str) else status.value)

    def set_plan(self, task_id: str, plan_json: str) -> None:
        self.update(task_id, plan_json=plan_json)

    def list(self, workspace: str | None = None, limit: int = 50) -> list[dict]:
        if workspace:
            rows = self.db.rows(
                "SELECT * FROM tasks WHERE workspace=? ORDER BY created_at DESC LIMIT ?",
                (workspace, limit),
            )
        else:
            rows = self.db.rows("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))
        return rows_to_dicts(rows)


class Steps:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(
        self,
        task_id: str,
        step_index: int,
        tool: str,
        action: str,
        params: dict,
        status: str,
    ) -> None:
        self.db.execute(
            "INSERT INTO task_steps (id, task_id, step_index, tool, action, params_json, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (new_id("s_"), task_id, step_index, tool, action, json.dumps(params), status, _now()),
        )

    def finish(self, task_id: str, step_index: int, status: str, evidence: dict, error: str | None) -> None:
        params = (status, json.dumps(evidence), error, _now(), task_id, step_index)
        self.db.execute(
            "UPDATE task_steps SET status=?, evidence_json=?, error=?, finished_at=? "
            "WHERE task_id=? AND step_index=?",
            params,
        )

    def for_task(self, task_id: str) -> list[dict]:
        rows = self.db.rows("SELECT * FROM task_steps WHERE task_id=? ORDER BY step_index", (task_id,))
        return rows_to_dicts(rows)


class Conversations:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, workspace: str, title: str | None) -> str:
        cid = new_id("c_")
        now = _now()
        self.db.execute(
            "INSERT INTO conversations (id, workspace, title, created_at, updated_at) VALUES (?,?,?,?,?)",
            (cid, workspace, title, now, now),
        )
        return cid

    def add_message(self, conversation_id: str, role: str, content: str, task_id: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, task_id, created_at) VALUES (?,?,?,?,?,?)",
            (new_id("m_"), conversation_id, role, content, task_id, _now()),
        )
        self.db.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?",
            (_now(), conversation_id),
        )

    def messages(self, conversation_id: str, limit: int = 100) -> list[dict]:
        return self.db.rows(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC LIMIT ?",
            (conversation_id, limit),
        )


class Providers:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(self, provider_id: str, kind: str, name: str, base_url: str | None, model: str, config: dict) -> None:
        now = _now()
        self.db.execute(
            "INSERT INTO providers (id, kind, name, base_url, model, enabled, config_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,1,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "kind=excluded.kind, name=excluded.name, base_url=excluded.base_url, model=excluded.model, "
            "config_json=excluded.config_json, updated_at=excluded.updated_at",
            (provider_id, kind, name, base_url, model, json.dumps(config), now, now),
        )

    def delete(self, provider_id: str) -> None:
        self.db.execute("DELETE FROM providers WHERE id=?", (provider_id,))

    def list(self) -> list[dict]:
        return rows_to_dicts(self.db.rows("SELECT * FROM providers ORDER BY created_at"))

    def get(self, provider_id: str) -> dict | None:
        row = self.db.fetchone("SELECT * FROM providers WHERE id=?", (provider_id,))
        return rows_to_dicts([row])[0] if row else None

    def set_default(self, provider_id: str, model: str) -> None:
        self.db.execute("UPDATE providers SET is_default=0")
        self.db.execute(
            "UPDATE providers SET is_default=1, enabled=1 WHERE id=?",
            (provider_id,),
        )
        self.db.execute("UPDATE kv SET value=? WHERE key='default_model'", (model,))
        self.db.execute(
            "INSERT OR IGNORE INTO kv (key, value) VALUES ('default_model', ?)",
            (model,),
        )

    def default(self) -> tuple[str, str] | None:
        row = self.db.fetchone("SELECT id, model FROM providers WHERE is_default=1 AND enabled=1")
        if row:
            return row["id"], row["model"]
        row2 = self.db.fetchone("SELECT value FROM kv WHERE key='default_model'")
        if row2 and row2["value"]:
            return "mock", row2["value"]
        return None


class SchedulerRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        workspace: str,
        name: str,
        prompt: str,
        schedule_type: str,
        trigger: dict,
        retry_policy: dict | None = None,
    ) -> str:
        jid = new_id("job_")
        now = _now()
        self.db.execute(
            "INSERT INTO scheduled_jobs (id, workspace, name, prompt, schedule_type, trigger_json, "
            "retry_policy_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (jid, workspace, name, prompt, schedule_type, json.dumps(trigger),
             json.dumps(retry_policy or {}), now, now),
        )
        return jid

    def update(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        params = list(fields.values()) + [_now(), job_id]
        self.db.execute(f"UPDATE scheduled_jobs SET {cols}, updated_at=? WHERE id=?", tuple(params))

    def get(self, job_id: str) -> dict | None:
        row = self.db.fetchone("SELECT * FROM scheduled_jobs WHERE id=?", (job_id,))
        return rows_to_dicts([row])[0] if row else None

    def list(self) -> list[dict]:
        return rows_to_dicts(self.db.rows("SELECT * FROM scheduled_jobs ORDER BY created_at"))

    def next_due(self, before: float, limit: int = 10) -> list[dict]:
        rows = self.db.rows(
            "SELECT * FROM scheduled_jobs WHERE enabled=1 AND status='idle' "
            "AND next_run_at IS NOT NULL AND next_run_at <= ? ORDER BY next_run_at LIMIT ?",
            (before, limit),
        )
        return rows_to_dicts(rows)

    def delete(self, job_id: str) -> None:
        self.db.execute("DELETE FROM scheduled_jobs WHERE id=?", (job_id,))


class Activity:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(
        self,
        *,
        task_id: str | None,
        skill: str | None,
        action: str | None,
        resource: str | None,
        status: str,
        approval: str | None = None,
        outcome: str | None = None,
        step_id: str | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO activity_events (task_id, step_id, skill, action, resource, status, approval, outcome, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (task_id, step_id, skill, action, resource, status, approval, outcome, _now()),
        )

    def list(self, limit: int = 200) -> list[dict]:
        return self.db.rows(
            "SELECT * FROM activity_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )


class PermissionsRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, risk: str, pattern: str, policy: str, scope: str = "task", note: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO permissions (risk, pattern, policy, scope, note, created_at) VALUES (?,?,?,?,?,?)",
            (risk, pattern, policy, scope, note, _now()),
        )

    def all(self) -> list[dict]:
        return self.db.rows("SELECT * FROM permissions ORDER BY created_at")

    def clear(self) -> None:
        self.db.execute("DELETE FROM permissions")


class Approvals:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, approval_id: str, task_id: str, action: str, reason: str, resource: str, risk: str) -> None:
        self.db.execute(
            "INSERT INTO approvals (id, task_id, action, reason, resource, risk, status, created_at) "
            "VALUES (?,?,?,?,?,?,'pending',?)",
            (approval_id, task_id, action, reason, resource, risk, _now()),
        )

    def decide(self, approval_id: str, approve: bool, note: str | None) -> dict | None:
        row = self.db.fetchone("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if not row:
            return None
        status = "approved" if approve else "denied"
        self.db.execute(
            "UPDATE approvals SET status=?, decided_at=? WHERE id=?",
            (status, _now(), approval_id),
        )
        row.update(status=status, decided_at=_now(), note=note)
        return row


class Memories:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, kind: str, scope: str, content: str, key: str | None = None, metadata: dict | None = None) -> None:
        now = _now()
        self.db.execute(
            "INSERT INTO memories (kind, scope, key, content, metadata_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (kind, scope, key, content, json.dumps(metadata or {}), now, now),
        )

    def list(self, kind: str | None = None, scope: str | None = None) -> list[dict]:
        sql = "SELECT * FROM memories"
        cond, params = [], []
        if kind:
            cond.append("kind=?")
            params.append(kind)
        if scope:
            cond.append("scope=?")
            params.append(scope)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY updated_at DESC"
        return rows_to_dicts(self.db.rows(sql, tuple(params)))

    def delete(self, memory_id: int) -> None:
        self.db.execute("DELETE FROM memories WHERE id=?", (memory_id,))


class EventLog:
    def __init__(self, db: Database) -> None:
        self.db = db

    def append(self, event: Event) -> None:
        self.db.execute(
            "INSERT INTO event_log (task_id, event_type, status, tool, action, message, evidence_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (event.task_id, event.event_type.value, event.status.value, event.tool, event.action,
             event.message, json.dumps(event.evidence), event.ts),
        )

    def for_task(self, task_id: str, limit: int = 500) -> list[dict]:
        rows = self.db.rows(
            "SELECT * FROM event_log WHERE task_id=? ORDER BY id ASC LIMIT ?",
            (task_id, limit),
        )
        out = []
        for r in rows:
            d = dict(r)
            d["evidence"] = json.loads(d.pop("evidence_json") or "{}")
            out.append(d)
        return out


def make_defaults(db: Database) -> None:
    """Seed providers and demo permissions."""
    db.execute(
        "INSERT OR IGNORE INTO kv (key, value) VALUES ('default_model', 'jawa-mock')"
    )
