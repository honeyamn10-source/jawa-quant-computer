"""Computer control skill (experimental): platform info and launching
applications through OS-native mechanisms. Mouse/keyboard/GUI automation is
out of scope for the 0.1 core and is documented as experimental."""

from __future__ import annotations

import platform
import shlex
import subprocess
import sys
from typing import Any

from jqc.core.errors import JqcError
from jqc.skills.base import Skill, SkillContext, ToolDef


class ComputerSkill(Skill):
    name = "computer"
    description = "Computer-level info and launching applications (experimental)."

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef("computer.info", "OS, architecture and Python info", {}, "low"),
            ToolDef("computer.launch", "Launch an application or open a file/URL (high risk)",
                    {"target": {"type": "string"}, "args": {"type": "array", "default": []}}, "high"),
        ]

    async def run(self, action: str, params: dict[str, Any], ctx: SkillContext) -> Any:
        action = action.removeprefix("computer.")
        if action == "info":
            return {
                "os": platform.system(),
                "release": platform.release(),
                "architecture": platform.machine(),
                "python": sys.version.split()[0],
                "hostname": platform.node(),
            }
        if action == "launch":
            target = params["target"]
            args = [str(a) for a in params.get("args", [])]
            cmd = _launch_cmd(target, args)
            try:
                subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)
            except OSError as exc:
                raise JqcError(f"computer.launch failed: {exc}") from exc
            return {"launched": target, "command": shlex.join(cmd)}
        raise JqcError(f"computer: unknown action '{action}'")


def _launch_cmd(target: str, args: list[str]) -> list[str]:
    system = platform.system()
    quoted = shlex.quote(target)
    extra = " ".join(shlex.quote(a) for a in args)
    if system == "Windows":
        return ["start", "", target, *args]
    if system == "Darwin":
        return ["open", target, *args]
    if shutil_which("xdg-open") or shutil_which("gio"):
        return ["xdg-open", target, *args] if shutil_which("xdg-open") else ["gio", "open", target, *args]
    return ["sh", "-c", f"{quoted} {extra}".strip()]


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)
