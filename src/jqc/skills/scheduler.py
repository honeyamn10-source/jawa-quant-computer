"""Scheduler skill: create and manage one-time / recurring tasks."""

from __future__ import annotations

from typing import Any

from jqc.core.errors import JqcError
from jqc.scheduler.times import compute_next, resolve_tz
from jqc.skills.base import Skill, SkillContext, ToolDef
from jqc.storage.db import Database
from jqc.storage.repos import SchedulerRepo


class SchedulerSkill(Skill):
    name = "scheduler"
    description = "Schedule one-time, interval or cron jobs."

    def __init__(self, db: Database) -> None:
        self.repo = SchedulerRepo(db)

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef("scheduler.create", "Create a scheduled job",
                    {
                        "name": {"type": "string"},
                        "prompt": {"type": "string"},
                        "schedule_type": {"type": "string", "enum": ["once", "interval", "cron"]},
                        "trigger": {"type": "object"},
                        "retry_policy": {"type": "object", "default": {}},
                    }, "medium"),
            ToolDef("scheduler.list", "List scheduled jobs", {}, "low"),
            ToolDef("scheduler.cancel", "Cancel/delete a job", {"job_id": {"type": "string"}}, "medium"),
            ToolDef("scheduler.toggle", "Enable or disable a job",
                    {"job_id": {"type": "string"}, "enabled": {"type": "boolean"}}, "medium"),
        ]

    async def run(self, action: str, params: dict[str, Any], ctx: SkillContext) -> Any:
        action = action.removeprefix("scheduler.")
        if action == "create":
            schedule_type = params["schedule_type"]
            trigger = params.get("trigger") or {}
            if trigger.get("timezone"):
                resolve_tz(trigger.get("timezone"))
            next_time = compute_next(schedule_type, trigger)
            job_id = self.repo.create(
                workspace=ctx.workspace,
                name=params["name"],
                prompt=params["prompt"],
                schedule_type=schedule_type,
                trigger=trigger,
                retry_policy=params.get("retry_policy"),
            )
            self.repo.update(job_id, next_run_at=next_time.timestamp())
            return {"job_id": job_id, "next_run_at": next_time.isoformat(),
                    "name": params["name"], "schedule_type": schedule_type}
        if action == "list":
            return {"jobs": self.repo.list()}
        if action == "cancel":
            job = self.repo.get(params["job_id"])
            if not job:
                raise JqcError(f"scheduler: job {params['job_id']} not found")
            self.repo.update(params["job_id"], enabled=0, status="cancelled")
            return {"job_id": params["job_id"], "status": "cancelled"}
        if action == "toggle":
            self.repo.update(params["job_id"], enabled=1 if params["enabled"] else 0)
            return {"job_id": params["job_id"], "enabled": params["enabled"]}
        raise JqcError(f"scheduler: unknown action '{action}'")
