"""Skill framework.

A skill exposes a machine-readable manifest of tools/actions. The executor
routes ``(tool, action, params)`` calls to skills, applies permission checks,
emits structured events and supports cancellation and approvals.

Event bus: skills call ``ctx.emit(event)``; the orchestrator forwards events
to storage/SSE/UI. ``ctx.approve_high_risk`` gates irreversible actions.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jqc.core.errors import TaskCancelled
from jqc.core.schemas import Event, EventStatus, EventType
from jqc.security.permissions import ApprovalService, PermissionManager
from jqc.security.secrets import SecretStore


@dataclass
class SkillContext:
    task_id: str
    workspace: str
    data_dir: Path
    workspace_dir: Path
    permissions: PermissionManager
    approvals: ApprovalService
    secrets: SecretStore
    emit: Callable[[Event], None] = field(default=lambda e: None)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    demo_mode: bool = True

    def check_cancelled(self, step_id: str | None = None) -> None:
        if self.cancel_event.is_set():
            raise TaskCancelled("Task cancelled by user.")

    def emit_step(
        self,
        step_id: str | None,
        status: EventStatus,
        tool: str,
        action: str,
        message: str | None = None,
        evidence: dict | None = None,
        event_type: EventType = EventType.tool,
    ) -> None:
        self.emit(
            Event(
                task_id=self.task_id,
                event_type=event_type,
                status=status,
                tool=tool,
                action=action,
                message=message,
                evidence=evidence or {},
                step_id=step_id,
            )
        )


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON-schema-ish
    risk: str = "medium"  # low | medium | high hint for planning/risk display


class Skill(ABC):
    """Base class for all skills."""

    name: str
    description: str = ""

    @abstractmethod
    def tools(self) -> list[ToolDef]:
        """Declare the operations this skill exposes."""

    @abstractmethod
    async def run(self, action: str, params: dict[str, Any], ctx: SkillContext) -> Any:
        """Execute one action. Raise on failure; return JSON-able evidence."""

    def is_local(self) -> bool:
        """True when the skill never leaves the machine by default."""
        return True


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"Skill '{skill.name}' already registered")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        return self._skills[name]

    def tools(self) -> list[ToolDef]:
        out: list[ToolDef] = []
        for skill in self._skills.values():
            out.extend(skill.tools())
        return out

    def names(self) -> list[str]:
        return sorted(self._skills.keys())
