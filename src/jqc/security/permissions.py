"""Risk-classified permission system.

Risk classes
    low       read-only inspection, drafts, search
    medium    create/move/download files, ordinary dev commands
    high      delete, install, post publicly, send messages, transfers, irreversible

Policies
    ask        require explicit user approval at runtime
    allow      permit without prompting
    deny       reject without prompting

Policy resolution order:
    1. Explicit rules in the permissions table (most specific pattern wins).
    2. Approval-mode defaults (demo/headless allow; otherwise ask for high).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from jqc.storage.db import Database
from jqc.storage.repos import PermissionsRepo

RISK_LEVELS = {"low": 0, "medium": 1, "high": 2}


@dataclass
class PermissionDecision:
    allowed: bool
    policy: str
    reason: str = ""
    needs_approval: bool = False
    rule_id: int | None = None


@dataclass
class RiskRule:
    """Built-in fallback risk classification for known actions.

    ``pattern`` is the action (fnmatch) pattern, ``field`` selects whether the
    pattern applies to the action name ("action") or the resource string
    ("pattern"). For shell commands, the resource is the command text.
    """

    pattern: str
    risk: str
    field: str = "action"

    def matches(self, tool: str, action: str, resource: str | None = None) -> bool:
        if self.field == "resource":
            target = resource or ""
            return fnmatch.fnmatch(target.lower(), self.pattern.lower())
        return fnmatch.fnmatch(action.lower(), self.pattern.lower())


DEFAULT_RULES: list[RiskRule] = [
    # Browser
    RiskRule("*open*", "low", "action"),
    RiskRule("*title*", "low", "action"),
    RiskRule("*screenshot*", "low", "action"),
    RiskRule("*navigate*", "medium", "action"),
    RiskRule("*extract*", "low", "action"),
    RiskRule("*download*", "medium", "action"),
    RiskRule("*click*", "medium", "action"),
    RiskRule("*type*", "medium", "action"),
    RiskRule("*upload*", "medium", "action"),
    RiskRule("*close*", "medium", "action"),
    # Filesystem
    RiskRule("*read*", "low", "action"),
    RiskRule("*search*", "low", "action"),
    RiskRule("*list*", "low", "action"),
    RiskRule("*stat*", "low", "action"),
    RiskRule("*create*", "medium", "action"),
    RiskRule("*write*", "medium", "action"),
    RiskRule("*move*", "medium", "action"),
    RiskRule("*copy*", "medium", "action"),
    RiskRule("*rename*", "medium", "action"),
    RiskRule("*mkdir*", "medium", "action"),
    RiskRule("*delete*", "high", "action"),
    RiskRule("*trash*", "high", "action"),
    # Git
    RiskRule("*status*", "low", "action"),
    RiskRule("*log*", "low", "action"),
    RiskRule("*diff*", "low", "action"),
    RiskRule("*checkout*", "medium", "action"),
    RiskRule("*branch*", "medium", "action"),
    RiskRule("*add*", "medium", "action"),
    RiskRule("*commit*", "medium", "action"),
    RiskRule("*force*push*", "high", "action"),
    RiskRule("*reset*hard*", "high", "action"),
]

DEFAULT_TOOL_RISK = {
    "browser": "medium",
    "filesystem": "medium",
    "shell": "medium",
    "git": "medium",
    "scheduler": "medium",
    "search": "low",
    "memory": "medium",
    "documents": "low",
    "voice": "low",
    "research": "low",
    "computer": "high",
}

# Sensitive shell commands matched against the command text (resource).
SHELL_HIGH_PATTERNS = [
    "*rm -rf*",
    "*rm -fr*",
    "*sudo*",
    "*dd if=*of=*",
    "*mkfs*",
    "*fdisk*",
    "*shutdown*",
    "*reboot*",
    "*useradd*",
    "*userdel*",
    "*chmod 777*",
    "*chown*",
    "*curl*wget*|*sh*",
    "*base64*-d*",
    "*kubectl delete*",
    "*terraform destroy*",
    "*git push --force*",
]


class PermissionManager:
    """Resolves whether a tool action may run, and with what policy."""

    def __init__(self, db: Database, approval_mode: str = "prompt", demo_mode: bool = True) -> None:
        self.repo = PermissionsRepo(db)
        self.approval_mode = approval_mode
        self.demo_mode = demo_mode

    def classify(self, tool: str, action: str, resource: str | None = None) -> str:
        # 1. Explicit action-pattern rules.
        for rule in DEFAULT_RULES:
            if rule.matches(tool, action, resource):
                return rule.risk
        # 2. Dangerous shell command text patterns.
        if tool == "shell" and resource:
            for pat in SHELL_HIGH_PATTERNS:
                if fnmatch.fnmatch(resource.lower(), pat.lower()):
                    return "high"
        # 3. Tool-level default.
        return DEFAULT_TOOL_RISK.get(tool, "medium")

    def check(self, tool: str, action: str, resource: str | None = None, task_id: str | None = None) -> PermissionDecision:
        risk = self.classify(tool, action, resource)
        rule = self._explicit_rule(risk, resource)
        if rule:
            policy = rule["policy"]
            if policy == "deny":
                return PermissionDecision(False, "deny", reason=f"Blocked by explicit rule (id={rule['id']})", rule_id=rule["id"])
            if policy == "allow":
                return PermissionDecision(True, "allow", reason="Explicit allow rule", rule_id=rule["id"])
            return self._ask(risk, tool, action, resource)
        if risk == "low":
            return PermissionDecision(True, "allow", reason="Low-risk action")
        if self.approval_mode == "deny":
            return PermissionDecision(False, "deny", reason="Approval mode is deny")
        if self.approval_mode == "allow-task":
            return PermissionDecision(True, "allow", reason="Approval mode allow-task")
        if self.demo_mode and risk == "medium":
            return PermissionDecision(True, "allow", reason="Demo mode auto-approves medium risk")
        if self.demo_mode and risk == "high":
            # Demo mode prompts for high risk but UI auto-resolves for
            # irreversible actions with an explicit note.
            return self._ask(risk, tool, action, resource)
        return self._ask(risk, tool, action, resource)

    def _explicit_rule(self, risk: str, resource: str | None) -> dict | None:
        best: dict | None = None
        bestlen = -1
        for r in self.repo.all():
            if r["risk"] != risk:
                continue
            pattern = r["pattern"]
            if (pattern == "*" or (resource and fnmatch.fnmatch(resource.lower(), pattern.lower()))) \
                    and len(pattern) > bestlen:
                best = r
                bestlen = len(pattern)
        return best

    def _ask(self, risk: str, tool: str, action: str, resource: str | None) -> PermissionDecision:
        return PermissionDecision(
            True,
            "ask",
            reason=f"{risk} risk action requires approval",
            needs_approval=True,
        )


def validate_approval_mode(mode: str) -> None:
    if mode not in {"prompt", "allow-task", "deny"}:
        raise ValueError(f"Invalid approval mode: {mode}")


class ApprovalService:
    """Tracks pending approvals and lets the UI/user resolve them."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.repo = __import__("jqc.storage.repos", fromlist=["Approvals"]).Approvals(db)

    def request(self, task_id: str, action: str, reason: str, resource: str | None, risk: str) -> str:
        from jqc.storage.repos import new_id

        aid = new_id("ap_")
        self.repo.create(aid, task_id, action, reason, resource or "", risk)
        return aid

    def decide(self, approval_id: str, approve: bool, note: str | None = None) -> dict | None:
        return self.repo.decide(approval_id, approve, note)

    def list(self, status: str = "pending", limit: int = 100) -> list[dict]:
        if status == "all":
            return self.db.rows("SELECT * FROM approvals ORDER BY created_at DESC LIMIT ?", (limit,))
        return self.db.rows(
            "SELECT * FROM approvals WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
