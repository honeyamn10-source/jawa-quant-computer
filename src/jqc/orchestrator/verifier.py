"""Verifier: confirms a step's claimed outcome with real evidence, not
assumed success. Raising here prevents the orchestrator from marking a task
complete when the outcome is missing."""

from __future__ import annotations

from typing import Any

from jqc.core.errors import VerificationFailed

RULES: list[tuple[tuple[str, str], Any]] = [
    (("filesystem", "write"), lambda p, e: _has(e, "path")),
    (("filesystem", "create"), lambda p, e: _has(e, "path")),
    (("filesystem", "mkdir"), lambda p, e: bool(e.get("is_dir"))),
    (("filesystem", "read"), lambda p, e: _has(e, "content")),
    (("filesystem", "list"), lambda p, e: _has(e, "entries")),
    (("filesystem", "move"), lambda p, e: _has(e, "destination")),
    (("filesystem", "copy"), lambda p, e: _has(e, "destination")),
    (("filesystem", "delete"), lambda p, e: _has(e, "deleted")),
    (("filesystem", "stat"), lambda p, e: _has(e, "path")),
    (("filesystem", "search"), lambda p, e: _has(e, "hits")),
    (("browser", "open"), lambda p, e: _has(e, "url")),
    (("browser", "title"), lambda p, e: bool(e.get("title"))),
    (("browser", "download"), lambda p, e: _has(e, "path") and int(e.get("bytes", 0)) >= 0),
    (("browser", "screenshot"), lambda p, e: _has(e, "path")),
    (("shell", "run"), lambda p, e: _has(e, "exit_code")),
    (("scheduler", "create"), lambda p, e: _has(e, "job_id")),
    (("memory", "save"), lambda p, e: e.get("saved", False) is True),
    (("search", "local"), lambda p, e: _has(e, "hits")),
    (("research", "run"), lambda p, e: bool(e.get("citations"))),
    (("documents", "read"), lambda p, e: _has(e, "content")),
    (("computer", "info"), lambda p, e: _has(e, "os")),
]


def check(tool: str, action: str, params: dict, evidence: dict) -> tuple[bool, str]:
    for (t, a), rule in RULES:
        if t == tool and (a == action or a == "*"):
            try:
                ok = bool(rule(params, evidence))
            except Exception:
                ok = False
            if not ok:
                return False, f"Verifier could not confirm '{tool}.{action}' from evidence."
            return True, "confirmed"
    if not evidence:
        return False, f"Verifier: '{tool}.{action}' returned no evidence."
    return True, "confirmed"


def check_strict(tool: str, action: str, params: dict, evidence: dict) -> None:
    ok, msg = check(tool, action, params, evidence)
    if not ok:
        raise VerificationFailed(msg)


def _has(e: dict, key: str) -> bool:
    return key in e and e[key] is not None
