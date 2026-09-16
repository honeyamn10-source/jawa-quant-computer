"""Shell skill: bounded execution, capture, timeout, cancellation."""

from __future__ import annotations

import sys

import pytest

from jqc.core.errors import JqcError
from jqc.skills.base import SkillContext
from jqc.skills.shell import ShellSkill


@pytest.mark.asyncio
async def test_shell_echo(deps):
    skill = ShellSkill()
    ctx = SkillContext(task_id="t", workspace="default",
                       data_dir=deps["settings"].data_dir,
                       workspace_dir=deps["settings"].workspace_dir,
                       permissions=deps["permissions"], approvals=deps["approvals"],
                       secrets=deps["secrets"])
    res = await skill.run("run", {"command": "echo jawa-ok"}, ctx)
    assert res["ok"] is True
    assert res["exit_code"] == 0
    assert "jawa-ok" in res["stdout"]


@pytest.mark.asyncio
async def test_shell_failure_reports_exit_code(deps):
    skill = ShellSkill()
    ctx = SkillContext(task_id="t", workspace="default",
                       data_dir=deps["settings"].data_dir,
                       workspace_dir=deps["settings"].workspace_dir,
                       permissions=deps["permissions"], approvals=deps["approvals"],
                       secrets=deps["secrets"])
    cmd = "exit 3" if sys.platform != "win32" else "exit /b 3"
    res = await skill.run("run", {"command": cmd}, ctx)
    assert res["ok"] is False
    assert res["exit_code"] != 0


@pytest.mark.asyncio
async def test_shell_timeout(deps):
    skill = ShellSkill()
    ctx = SkillContext(task_id="t", workspace="default",
                       data_dir=deps["settings"].data_dir,
                       workspace_dir=deps["settings"].workspace_dir,
                       permissions=deps["permissions"], approvals=deps["approvals"],
                       secrets=deps["secrets"])
    cmd = "sleep 10" if sys.platform != "win32" else "timeout /t 10"
    with pytest.raises(JqcError):
        await skill.run("run", {"command": cmd, "timeout_seconds": 1}, ctx)


@pytest.mark.asyncio
async def test_shell_uses_workspace_cwd(deps, ws):
    (ws / "marker.txt").write_text("in workspace")
    skill = ShellSkill()
    ctx = SkillContext(task_id="t", workspace="default",
                       data_dir=deps["settings"].data_dir,
                       workspace_dir=ws,
                       permissions=deps["permissions"], approvals=deps["approvals"],
                       secrets=deps["secrets"])
    res = await skill.run("run", {"command": "pwd"}, ctx)
    from pathlib import Path

    assert Path(res["stdout"].strip()) == ws
