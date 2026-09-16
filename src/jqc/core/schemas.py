"""Structured event model shared by the orchestrator, API and UI."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventStatus(str, Enum):
    started = "started"
    running = "running"
    pending_approval = "pending_approval"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
    cancelled = "cancelled"


class EventType(str, Enum):
    task = "task"
    step = "step"
    tool = "tool"
    message = "message"
    system = "system"
    approval = "approval"


class TaskStatus(str, Enum):
    queued = "queued"
    planning = "planning"
    running = "running"
    waiting_approval = "waiting_approval"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Event(BaseModel):
    """A normalized, persisted, human-inspectable record of one action."""

    task_id: str
    event_type: EventType = EventType.tool
    status: EventStatus = EventStatus.running
    tool: str | None = None
    action: str | None = None
    message: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    step_id: str | None = None
    parent_id: str | None = None
    ts: float = Field(default_factory=time.time)

    def redacted(self) -> dict[str, Any]:
        """Event dict safe for logs/UI (values are redacted in builders)."""
        return self.model_dump()


class TaskStep(BaseModel):
    """A single planned step in the task DAG."""

    id: str
    tool: str
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    description: str | None = None


class Plan(BaseModel):
    steps: list[TaskStep]
    summary: str | None = None
    verifier: str | None = None


class ChatResponse(BaseModel):
    task_id: str
    status: TaskStatus = TaskStatus.queued
    message: str


class ApprovalRequest(BaseModel):
    approval_id: str
    task_id: str
    action: str
    reason: str
    resource: str | None = None
    risk: str = "high"
    created_at: float = Field(default_factory=time.time)


class ApprovalDecision(BaseModel):
    approve: bool
    note: str | None = None
