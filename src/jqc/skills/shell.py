"""Secure shell skill: bounded-time command execution with capture."""

from __future__ import annotations

import asyncio
import shlex
from contextlib import suppress
from pathlib import Path
from typing import Any

from jqc.core.errors import JqcError
from jqc.skills.base import Skill, SkillContext, ToolDef


class ShellSkill(Skill):
    name = "shell"
    description = "Run terminal commands with timeouts, capture and exit-code inspection."

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                "shell.run",
                "Run a shell command",
                {
                    "command": {"type": "string"},
                    "cwd": {"type": "string", "default": "."},
                    "timeout_seconds": {"type": "integer", "default": 60},
                    "env": {"type": "object", "default": {}},
                },
                "medium",
            ),
            ToolDef("shell.command_history", "Recent commands run in this session",
                    {}, "low"),
        ]

    def __init__(self) -> None:
        self.history: list[dict[str, Any]] = []

    async def run(self, action: str, params: dict[str, Any], ctx: SkillContext) -> Any:
        action = action.removeprefix(f"{self.name}.")
        if action == "command_history":
            return {"history": self.history[-50:]}
        if action != "run":
            raise JqcError(f"shell: unknown action '{action}'")

        command = params["command"]
        if not command or not command.strip():
            raise JqcError("shell.run: command must not be empty")
        cwd = Path(params.get("cwd", "."))
        if not cwd.is_absolute():
            cwd = ctx.workspace_dir / cwd
        cwd = cwd.resolve()
        timeout = int(params.get("timeout_seconds", 60))
        timeout = max(1, min(timeout, 600))
        env = dict(params.get("env") or {})
        if env:
            resolved_env = {}
            for k, v in env.items():
                resolved_env[k] = str(v).replace("$WS", str(ctx.workspace_dir))
            env = resolved_env
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=None if not env else {**_safe_env(), **env},
            shell=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            with suppress(ProcessLookupError):
                await proc.communicate()
            raise JqcError(f"shell.run: command timed out after {timeout}s: {shlex.quote(command)}") from None
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        record = {
            "command": command,
            "exit_code": proc.returncode,
            "timeout": timeout,
            "cwd": str(cwd),
        }
        self.history.append(record)
        if proc.returncode != 0 and params.get("allow_fail") != "ok":
            return {"command": command, "exit_code": proc.returncode,
                    "stdout": out[-20000:], "stderr": err[-20000:],
                    "ok": False, "timed_out": False, "cwd": str(cwd)}
        return {"command": command, "exit_code": proc.returncode,
                "stdout": out[-20000:], "stderr": err[-20000:],
                "ok": True, "timed_out": False, "cwd": str(cwd)}


def _is_windows() -> bool:
    import platform

    return platform.system() == "Windows"


def _safe_env() -> dict:
    import os

    return dict(os.environ)
