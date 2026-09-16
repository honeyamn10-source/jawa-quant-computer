"""Acceptance tests: the required end-to-end flows run through the real agent,
storage, permissions and skills stack (mock browser driver; no network)."""

from __future__ import annotations

import json

import pytest

TITLE_FLOW = (
    "Open example.com, capture the page title and save it into a text file "
    "in my workspace."
)
FOLDER_FLOW = (
    'Create a folder named AI Computer Test, create notes.txt inside it, write '
    '"AI Computer is operational", then read the file back to me.'
)
SCHEDULE_FLOW = "Schedule a task five minutes from now that creates scheduled-test.txt."


@pytest.mark.asyncio
async def test_e2e_browser_title_to_file(agent, ws):
    task = await agent.submit_and_wait(TITLE_FLOW)
    assert task["status"] == "completed", task.get("error")
    title_file = ws / "page-title-examplecom.txt"
    assert title_file.exists()
    assert title_file.read_text() == "Example Domain"
    steps = agent.steps.for_task(task["id"])
    assert len(steps) == 3
    assert all(s["status"] == "completed" for s in steps)


@pytest.mark.asyncio
async def test_e2e_folder_file_readback(agent, ws):
    task = await agent.submit_and_wait(FOLDER_FLOW)
    assert task["status"] == "completed", task.get("error")
    notes = ws / "AI Computer Test" / "notes.txt"
    assert notes.exists()
    assert notes.read_text() == "AI Computer is operational"
    steps = agent.steps.for_task(task["id"])
    assert steps[-1]["tool"] == "filesystem" and steps[-1]["action"] == "read"


@pytest.mark.asyncio
async def test_e2e_scheduler_creates_job(agent, deps):
    task = await agent.submit_and_wait(SCHEDULE_FLOW)
    assert task["status"] == "completed", task.get("error")
    jobs = deps["scheduler"].repo.list()
    assert len(jobs) == 1
    assert jobs[0]["schedule_type"] == "once"
    assert jobs[0]["prompt"] == ("Create a file named scheduled-test.txt "
                                 "with the content 'scheduled by jawa'")


@pytest.mark.asyncio
async def test_scheduler_fires_job(agent, ws, deps):
    await agent.submit_and_wait(SCHEDULE_FLOW)
    job = deps["scheduler"].repo.list()[0]
    deps["scheduler"].repo.update(job["id"], next_run_at=0)
    await deps["scheduler"]._fire(deps["scheduler"].repo.get(job["id"]))
    fired = ws / "scheduled-test.txt"
    assert fired.exists()
    assert fired.read_text() == "scheduled by jawa"


@pytest.mark.asyncio
async def test_activity_recorded(agent):
    task = await agent.submit_and_wait(TITLE_FLOW)
    events = agent.eventlog.for_task(task["id"])
    kinds = {e["event_type"] for e in events}
    assert "task" in kinds and "step" in kinds
    statuses = {e["status"] for e in events}
    assert "completed" in statuses


@pytest.mark.asyncio
async def test_task_persists_result(agent):
    task = await agent.submit_and_wait(FOLDER_FLOW)
    result = json.loads(task["result"])
    assert result["summary"]
    assert result["steps"]


@pytest.mark.asyncio
async def test_conversation_messages(agent):
    conv = agent.conversations.create("default", "title")
    resp = agent.submit(TITLE_FLOW, "default", conv)
    assert resp.task_id
    msgs = agent.conversations.messages(conv)
    assert any(m["role"] == "user" for m in msgs)
