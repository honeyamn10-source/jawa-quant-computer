"""Git skill: repository inspection and safe, non-destructive operations."""

from __future__ import annotations

from typing import Any

from jqc.core.errors import JqcError
from jqc.skills.base import Skill, SkillContext, ToolDef


class GitSkill(Skill):
    name = "git"
    description = "Inspect repositories, create branches, commit prepared changes."

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef("git.status", "Show repository status", {"path": {"type": "string", "default": "."}}, "low"),
            ToolDef("git.log", "Show recent commit history",
                    {"path": {"type": "string", "default": "."}, "n": {"type": "integer", "default": 20}}, "low"),
            ToolDef("git.diff", "Show uncommitted changes",
                    {"path": {"type": "string", "default": "."}, "stat": {"type": "boolean", "default": True}}, "low"),
            ToolDef("git.branch_create", "Create and switch to a new branch",
                    {"path": {"type": "string", "default": "."}, "name": {"type": "string"}}, "medium"),
            ToolDef("git.add", "Stage files", {"path": {"type": "string", "default": "."}, "files": {"type": "string"}}, "medium"),
            ToolDef("git.commit", "Create a commit",
                    {"path": {"type": "string", "default": "."}, "message": {"type": "string"}}, "medium"),
            ToolDef("git_branch_create", "Create a branch (alias)",
                    {"path": {"type": "string", "default": "."}, "name": {"type": "string"}}, "medium"),
        ]

    async def _run_git(self, path: str, args: list[str], ctx: SkillContext) -> dict:
        from jqc.skills.shell import ShellSkill

        repo = path.strip() or "."
        shell = ShellSkill()
        res = await shell.run("run", {"command": f"git {' '.join(_q(a) for a in args)}", "cwd": repo}, ctx)
        if not res.get("ok"):
            raise JqcError(f"git {args[0]} failed (exit {res.get('exit_code')}): {res.get('stderr', '').strip()}")
        return res

    async def run(self, action: str, params: dict[str, Any], ctx: SkillContext) -> Any:
        action = action.removeprefix("git.")
        path = params.get("path", ".")
        if action == "status":
            row = await self._run_git(path, ["status", "--short", "--branch"], ctx)
            return {"output": (row.get("stdout") or "").strip(), "exit_code": row.get("exit_code")}
        if action == "log":
            n = int(params.get("n", 20))
            row = await self._run_git(path, ["log", "--oneline", "-n", str(n)], ctx)
            lines = [ln for ln in (row.get("stdout") or "").splitlines() if ln.strip()]
            return {"commits": lines}
        if action == "diff":
            row = await self._run_git(path, ["diff", "--stat"], ctx)
            return {"output": (row.get("stdout") or "").strip(),
                    "full": (row.get("stdout") or "").strip()}
        if action in {"branch_create", "git_branch_create"}:
            name = params.get("name")
            if not name:
                raise JqcError("git.branch_create: name required")
            await self._run_git(path, ["checkout", "-b", name], ctx)
            return {"branch": name}
        if action == "add":
            files = params.get("files", ".")
            await self._run_git(path, ["add", "--", files], ctx)
            return {"staged": files}
        if action == "commit":
            msg = params.get("message")
            if not msg:
                raise JqcError("git.commit: message required")
            await self._run_git(path, ["commit", "-m", msg], ctx)
            return {"message": msg}
        raise JqcError(f"git: unknown action '{action}'")


def _q(s: str) -> str:
    import shlex

    return shlex.quote(s)
