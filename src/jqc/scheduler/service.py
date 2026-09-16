"""Background scheduler: polls the SQLite job store and fires due jobs by
submitting them to the agent orchestrator, then recomputes ``next_run_at``."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

from jqc.config import Settings
from jqc.orchestrator.agent import AgentService
from jqc.scheduler.times import compute_next, now_utc
from jqc.storage.db import Database
from jqc.storage.repos import SchedulerRepo

log = logging.getLogger(__name__)


class SchedulerService:
    def __init__(self, settings: Settings, db: Database, agent: AgentService) -> None:
        self.settings = settings
        self.db = db
        self.repo = SchedulerRepo(db)
        self.agent = agent
        self._running = False
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._running = True
        self._stop.clear()
        asyncio.get_event_loop().create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        self._running = False

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                due = self.repo.next_due(time.time())
                for job in due:
                    await self._fire(job)
            except Exception:
                log.exception("scheduler loop error")
            try:
                await asyncio.wait_for(self._stop.wait(),
                                       timeout=self.settings.scheduler_poll_seconds)
            except TimeoutError:
                continue

    async def _fire(self, job: dict) -> None:
        job_id = job["id"]
        self.repo.update(job_id, status="running", last_run_at=time.time())
        log.info("scheduled job %s fired", job_id)
        try:
            result = await self.agent.submit_and_wait(job["prompt"], workspace=job["workspace"])
        except Exception as exc:
            log.warning("scheduled job %s failed: %s", job_id, exc)
            self.repo.update(job_id, status="idle", last_result=f"failed: {exc}")
            self._schedule_next(job, succeeded=False)
            return
        status = result.get("status", "failed")
        self.repo.update(job_id, status=status, last_result=result.get("result"))
        self._schedule_next(job, succeeded=(status == "completed"))

    def _schedule_next(self, job: dict, succeeded: bool) -> None:
        trigger = dict(job.get("trigger") or {})
        schedule_type = job["schedule_type"]
        if schedule_type == "once":
            if succeeded:
                self.repo.update(job["id"], enabled=0, status="completed", next_run_at=None)
            else:
                self.repo.update(job["id"], status="idle")
            return
        retry = job.get("retry_policy") or {}
        if not succeeded and int(retry.get("max_retries", 0)) > 0 and job.get("last_result"):
            # Retry shortly with backoff.
            backoff = float(retry.get("backoff_seconds", 10))
            self.repo.update(job["id"], status="idle",
                             next_run_at=now_utc().timestamp() + backoff,
                             last_result="retry scheduled")
            return
        if schedule_type != "once":
            trigger["_last_run"] = time.time()
            try:
                nxt = compute_next(schedule_type, trigger)
            except Exception:
                log.exception("could not compute next run for job %s", job["id"])
                nxt = now_utc() + timedelta(days=1)
            self.repo.update(job["id"], status="idle", next_run_at=nxt.timestamp())
