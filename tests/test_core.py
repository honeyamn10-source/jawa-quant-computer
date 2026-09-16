"""Unit tests: permissions, redaction, DB repos, planner, verifier, templating."""

from __future__ import annotations

import pytest

from jqc.core.errors import PlanParseError
from jqc.orchestrator.planner import heuristic_plan
from jqc.orchestrator.verifier import check
from jqc.security.secrets import LIVE_SECRETS, redact_dict, redact_text
from jqc.storage.db import Database
from jqc.storage.repos import Activity, SchedulerRepo, Tasks


class TestPermissions:
    def test_risk_classification(self, permissions):
        assert permissions.classify("filesystem", "read", "/a/b.txt") == "low"
        assert permissions.classify("filesystem", "write", "/a/b.txt") == "medium"
        assert permissions.classify("filesystem", "delete", "/a/b.txt") == "high"
        assert permissions.classify("shell", "run", "echo hi") == "medium"
        assert permissions.classify("shell", "run", "sudo rm -rf /") == "high"
        assert permissions.classify("git", "status", ".") == "low"
        assert permissions.classify("browser", "title") == "low"

    def test_demo_mode_medium_allowed(self, permissions):
        decision = permissions.check("filesystem", "write", "/tmp/x.txt")
        assert decision.allowed
        assert not decision.needs_approval

    def test_high_risk_requires_approval(self, permissions):
        decision = permissions.check("filesystem", "delete", "/tmp/x.txt")
        assert decision.allowed is True  # prompt mode permits, but needs approval
        assert decision.needs_approval

    def test_explicit_deny_wins(self, permissions):
        permissions.repo.add("high", "*", "deny", "global", "test")
        decision = permissions.check("filesystem", "delete", "/tmp/x.txt")
        assert not decision.allowed


class TestSecrets:
    def test_vault_roundtrip(self, secrets, tmp_path):
        secrets.set("provider.foo.api_key", "sk-super-secret-42")
        assert secrets.get("provider.foo.api_key") == "sk-super-secret-42"
        assert "sk-super-secret-42" in LIVE_SECRETS
        secrets.delete("provider.foo.api_key")
        assert secrets.get("provider.foo.api_key") is None

    def test_redact_assignment(self):
        txt = 'Authorization: Bearer abc123token values here'
        out = redact_text(txt)
        assert "abc123token" not in out
        assert "REDACTED" in out

    def test_redact_dict(self):
        out = redact_dict({"api_key": "abc", "nested": {"password": "x"}, "keep": "val"})
        assert out["api_key"] == "***REDACTED***"
        assert out["nested"]["password"] == "***REDACTED***"
        assert out["keep"] == "val"


class TestDatabase:
    def test_migrations_apply(self, tmp_path):
        db = Database(tmp_path / "t.sqlite3")
        tables = {r["name"] for r in db.rows("SELECT name FROM sqlite_master WHERE type='table'")}
        for expected in {
            "tasks", "task_steps", "event_log", "providers", "scheduled_jobs",
            "activity_events", "permissions", "approvals", "memories", "kv",
        }:
            assert expected in tables
        db.close()

    def test_tasks_update_persists(self, tmp_path):
        """Regression: params order bug swapped id/timestamp, so updates no-op'd."""
        db = Database(tmp_path / "t.sqlite3")
        tasks = Tasks(db)
        tid = tasks.create("default", "hello", None)
        tasks.set_status(tid, "completed")
        row = tasks.get(tid)
        assert row["status"] == "completed"
        db.close()

    def test_scheduler_update_persists(self, tmp_path):
        db = Database(tmp_path / "t.sqlite3")
        repo = SchedulerRepo(db)
        jid = repo.create("default", "n", "p", "once", {"at": "2026-09-16T00:00:00Z"})
        repo.update(jid, enabled=0)
        assert repo.get(jid)["enabled"] == 0
        db.close()

    def test_activity_commits(self, tmp_path):
        db = Database(tmp_path / "t.sqlite3")
        Activity(db).record(task_id="t1", skill="filesystem", action="write",
                            resource="/x", status="completed", outcome="verified")
        rows = Activity(db).list()
        assert rows and rows[0]["action"] == "write"
        db.close()


class TestPlanner:
    def test_browser_plan(self):
        plan = heuristic_plan("Open example.com, capture the page title and save it into a text file.")
        assert [s.tool for s in plan.steps] == ["browser", "browser", "filesystem"]
        assert plan.steps[2].params["content"] == "{{s2.title}}"

    def test_folder_plan(self):
        plan = heuristic_plan(
            'Create a folder named AI Computer Test, create notes.txt inside it, write '
            '"AI Computer is operational", then read the file back to me.')
        assert len(plan.steps) == 3
        assert plan.steps[0].params["path"] == "AI Computer Test"
        assert plan.steps[1].params["path"] == "AI Computer Test/notes.txt"
        assert plan.steps[1].params["content"] == "AI Computer is operational"

    def test_schedule_plan_once(self):
        plan = heuristic_plan("Schedule a task five minutes from now that creates scheduled-test.txt.")
        assert plan.steps[0].tool == "scheduler"
        assert plan.steps[0].params["schedule_type"] == "once"
        assert "timezone" in plan.steps[0].params["trigger"]

    def test_unknown_intent_raises(self):
        with pytest.raises(PlanParseError):
            heuristic_plan("Do something completely arbitrary and undefined please.")


class TestVerifier:
    def test_read_requires_content(self):
        ok, _ = check("filesystem", "read", {}, {"content": "x"})
        assert ok
        ok, msg = check("filesystem", "read", {}, {"path": "/x"})
        assert not ok
        assert "confirm" in msg

    def test_shell_requires_exit_code(self):
        ok, _ = check("shell", "run", {}, {"exit_code": 0})
        assert ok

    def test_default_requires_evidence(self):
        ok, _ = check("oddskill", "mystery", {}, {"something": 1})
        assert ok
        ok, _ = check("oddskill", "mystery", {}, {})
        assert not ok


class TestTemplating:
    def test_param_template(self):
        from jqc.orchestrator.agent import _template_params

        params = {"content": "{{s2.title}}", "nested": {"x": "{{s1.value}}"}, "plain": 3}
        outputs = {"s2": {"title": "Hello World"}, "s1": {"value": "v"}}
        out = _template_params(params, outputs)
        assert out["content"] == "Hello World"
        assert out["nested"]["x"] == "v"
        assert out["plain"] == 3
