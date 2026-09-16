"""Scheduler math + skill-level scheduler tests."""

from __future__ import annotations

from datetime import timedelta

import pytest

from jqc.core.errors import JqcError
from jqc.scheduler.times import compute_next, now_utc


class TestScheduleMath:
    def test_once_in_future(self):
        nxt = compute_next("once", {"at": (now_utc() + timedelta(hours=2)).isoformat(),
                                    "timezone": "UTC"})
        assert nxt > now_utc()

    def test_once_in_past_is_allowed(self):
        nxt = compute_next("once", {"at": (now_utc() - timedelta(hours=2)).isoformat()})
        assert nxt < now_utc() + timedelta(minutes=1)

    def test_interval_human_string(self):
        nxt = compute_next("interval", {"every": "5 minutes"})
        assert now_utc() + timedelta(minutes=4) <= nxt <= now_utc() + timedelta(minutes=6)

    def test_interval_seconds(self):
        nxt = compute_next("interval", {"seconds": 300})
        delta = abs((nxt - now_utc()) - timedelta(seconds=300))
        assert delta < timedelta(seconds=1)

    def test_cron_minute(self):
        now = now_utc()
        trigger = {"minute": (now.minute + 5) % 60, "hour": now.hour, "timezone": "UTC"}
        nxt = compute_next("cron", trigger)
        assert nxt.minute == trigger["minute"]

    def test_invalid_interval(self):
        with pytest.raises(JqcError):
            compute_next("interval", {})


@pytest.mark.asyncio
async def test_scheduler_skill_creates_job(agent, ws):
    resp = await agent.submit_and_wait(
        "Schedule a task five minutes from now that creates scheduled-test.txt.")
    assert resp["status"] == "completed"
    job = _first_job(agent)
    assert job["schedule_type"] == "once"
    assert job["next_run_at"] is not None


@pytest.mark.asyncio
async def test_scheduler_skill_toggle(agent, ws):
    await agent.submit_and_wait(
        "Schedule a task five minutes from now that creates scheduled-test.txt.")
    job = _first_job(agent)
    assert job["enabled"] == 1
    # create a recurring job through the skill directly
    skill = agent.registry.get("scheduler")
    from jqc.skills.base import SkillContext

    ctx = SkillContext(task_id="t", workspace="default", data_dir=ws.parent,
                       workspace_dir=ws, permissions=agent.permissions,
                       approvals=agent.approvals, secrets=agent.secrets)
    out = await skill.run("create", {"name": "hourly", "prompt": "list files",
                                     "schedule_type": "interval",
                                     "trigger": {"every": "1 hour"}}, ctx)
    assert "job_id" in out


def _first_job(agent):
    from jqc.storage.repos import SchedulerRepo

    jobs = SchedulerRepo(agent.db).list()
    return jobs[0]
