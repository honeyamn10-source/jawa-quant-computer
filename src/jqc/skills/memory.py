"""Memory skill: inspectable, removable user preference / workspace memories."""

from __future__ import annotations

from typing import Any

from jqc.core.errors import JqcError
from jqc.skills.base import Skill, SkillContext, ToolDef
from jqc.storage.db import Database
from jqc.storage.repos import Memories


class MemorySkill(Skill):
    name = "memory"
    description = "Save, read and delete short-term or long-term memories."

    def __init__(self, db: Database) -> None:
        self.repo = Memories(db)

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef("memory.save", "Save a memory for later use",
                    {"content": {"type": "string"}, "kind": {"type": "string", "default": "preference"},
                     "key": {"type": "string", "default": None}}, "medium"),
            ToolDef("memory.read", "List memories (optionally by kind)",
                    {"kind": {"type": "string", "default": None}}, "low"),
            ToolDef("memory.delete", "Remove a memory by id", {"id": {"type": "integer"}}, "high"),
        ]

    async def run(self, action: str, params: dict[str, Any], ctx: SkillContext) -> Any:
        action = action.removeprefix("memory.")
        if action == "save":
            self.repo.save(params.get("kind", "preference"), ctx.workspace,
                           params["content"], params.get("key"))
            latest = self.repo.list(kind=params.get("kind"), scope=ctx.workspace)
            return {"saved": True, "id": latest[0]["id"] if latest else None}
        if action == "read":
            return {"memories": self.repo.list(kind=params.get("kind"), scope=ctx.workspace)}
        if action == "delete":
            self.repo.delete(params["id"])
            return {"deleted": params["id"]}
        raise JqcError(f"memory: unknown action '{action}'")
