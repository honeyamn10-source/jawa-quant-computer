"""Agent coordinator: deterministic DAG execution of a plan across skills,
with permission gating, approvals, verification, retries and cancellation."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from jqc.config import Settings
from jqc.core.errors import (
    JqcError,
    MaxRuntimeExceeded,
    MaxStepsExceeded,
    PermissionDenied,
    PlanParseError,
    ProviderUnavailable,
    TaskCancelled,
    VerificationFailed,
)
from jqc.core.schemas import (
    ApprovalDecision,
    ApprovalRequest,
    ChatResponse,
    Event,
    EventStatus,
    EventType,
    Plan,
    TaskStatus,
)
from jqc.models.router import ModelRouter
from jqc.orchestrator.events import EventBus, EventHistory
from jqc.orchestrator.planner import Planner
from jqc.orchestrator.verifier import check_strict
from jqc.security.permissions import ApprovalService, PermissionManager
from jqc.security.secrets import SecretStore, redacted_str
from jqc.skills.base import SkillContext, SkillRegistry
from jqc.storage.db import Database
from jqc.storage.repos import Activity, Conversations, EventLog, Steps, Tasks
from jqc.storage.repos import Approvals as ApprovalsRepo

log = logging.getLogger(__name__)

TEMPLATE_RE = __import__("re").compile(r"\{\{([A-Za-z0-9_]+)(?:\.([A-Za-z0-9_]+))?\}\}")


def _resolve_resource(tool: str, action: str, params: dict) -> str | None:
    if tool == "shell":
        return str(params.get("command") or "")
    if tool == "filesystem":
        return str(params.get("path") or params.get("source") or params.get("destination") or "")
    if tool == "browser":
        return str(params.get("url") or params.get("selector") or "")
    if tool == "git" or tool == "documents" or tool == "search":
        return str(params.get("path") or params.get("url") or ".")
    return None


class AgentService:
    """Turns a chat request into an executed, verified, audited task."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        secrets: SecretStore,
        registry: SkillRegistry,
        router: ModelRouter,
        permissions: PermissionManager,
        approvals: ApprovalService,
        bus: EventBus,
        history: EventHistory,
    ) -> None:
        self.settings = settings
        self.db = db
        self.secrets = secrets
        self.registry = registry
        self.router = router
        self.permissions = permissions
        self.approvals = approvals
        self.bus = bus
        self.history = history

        self.tasks = Tasks(db)
        self.steps = Steps(db)
        self.conversations = Conversations(db)
        self.activity = Activity(db)
        self.eventlog = EventLog(db)
        self.approvals_repo = ApprovalsRepo(db)
        self.planner = Planner(router)

        self._runs: dict[str, asyncio.Future] = {}
        self._approval_futures: dict[str, asyncio.Future] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    def submit(self, request: str, workspace: str = "default", conversation_id: str | None = None) -> ChatResponse:
        task_id = self.tasks.create(workspace, request, conversation_id)
        if conversation_id:
            self.conversations.add_message(conversation_id, "user", request)
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._runs[task_id] = fut
        loop.create_task(self._execute(task_id, request, workspace))
        return ChatResponse(task_id=task_id, status=TaskStatus.queued,
                            message="Task queued.")

    async def submit_and_wait(self, request: str, workspace: str = "default",
                              conversation_id: str | None = None) -> dict:
        resp = self.submit(request, workspace, conversation_id)
        fut = self._runs[resp.task_id]
        try:
            await asyncio.wait_for(asyncio.shield(fut), timeout=self.settings.max_runtime_seconds + 60)
        except TimeoutError:
            await self.cancel(resp.task_id)
            raise MaxRuntimeExceeded("Task exceeded allowed runtime.") from None
        return self.tasks.get(resp.task_id) or {}

    def is_running(self, task_id: str) -> bool:
        fut = self._runs.get(task_id)
        return fut is not None and not fut.done()

    async def cancel(self, task_id: str) -> None:
        ev = self._cancel_events.get(task_id)
        if ev:
            ev.set()
        fut = self._runs.get(task_id)
        if fut and not fut.done():
            fut.cancel()
        task = self.tasks.get(task_id)
        if task and task["status"] in {TaskStatus.queued.value, TaskStatus.planning.value,
                                       TaskStatus.running.value, TaskStatus.waiting_approval.value}:
            self.tasks.set_status(task_id, TaskStatus.cancelled)
        self._emit(Event(task_id=task_id, event_type=EventType.task, status=EventStatus.cancelled,
                         message="Task cancelled by user."))

    # ------------------------------------------------------------------
    # Approval API
    # ------------------------------------------------------------------

    def pending_approval(self, approval_id: str) -> ApprovalRequest | None:
        row = self.approvals_repo_db_get(approval_id)
        if not row:
            return None
        return ApprovalRequest(approval_id=row["id"], task_id=row["task_id"], action=row["action"],
                               reason=row["reason"], resource=row["resource"], risk=row["risk"],
                               created_at=row["created_at"])

    def approvals_repo_db_get(self, approval_id: str) -> dict | None:
        return self.db.fetchone("SELECT * FROM approvals WHERE id=?", (approval_id,))

    def decide(self, approval_id: str, approve: bool, note: str | None = None) -> dict | None:
        row = self.approvals.decide(approval_id, approve, note)
        fut = self._approval_futures.get(approval_id)
        if fut and not fut.done():
            fut.set_result(ApprovalDecision(approve=approve, note=note))
        return row

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _execute(self, task_id: str, request: str, workspace: str) -> None:
        started = time.monotonic()
        cancel_event = asyncio.Event()
        self._cancel_events[task_id] = cancel_event
        try:
            self.tasks.set_status(task_id, TaskStatus.planning)
            self._emit(Event(task_id=task_id, event_type=EventType.task, status=EventStatus.started,
                             message="Understanding request"))
            plan_source = "heuristic"
            try:
                plan = await self.planner.plan(request, prefer_heuristic_first=True)
            except PlanParseError:
                provider, model = self.router.default()
                if provider.kind == "mock":
                    raise
                plan_source = "model"
                plan = await self.planner.plan(request, prefer_heuristic_first=False)

            self.tasks.set_plan(task_id, plan.model_dump_json())
            self._persist_plan(task_id, plan)
            self.tasks.set_status(task_id, TaskStatus.running)
            self._emit(Event(task_id=task_id, event_type=EventType.task, status=EventStatus.running,
                             message=plan.summary or "Executing plan"))

            outputs: dict[str, dict[str, Any]] = {}
            ordered = _topo(plan)
            for index, step in enumerate(ordered):
                if cancel_event.is_set():
                    raise TaskCancelled("Task cancelled by user.")
                if index >= self.settings.max_steps_per_task:
                    raise MaxStepsExceeded(
                        f"Task exceeded {self.settings.max_steps_per_task} steps (resource control)."
                    )
                if time.monotonic() - started > self.settings.max_runtime_seconds:
                    raise MaxRuntimeExceeded(
                        f"Task exceeded {self.settings.max_runtime_seconds}s (resource control)."
                    )
                evidence = await self._run_step(task_id, index, step, params=_template_params(step.params, outputs),
                                                workspace=workspace, cancel_event=cancel_event)
                outputs[step.id] = evidence
                self.steps.finish(task_id, index, EventStatus.completed.value, evidence, None)

            self.tasks.set_status(task_id, TaskStatus.completed)
            summary = plan.summary or "Done."
            self._finish_and_report(task_id, summary, outputs, plan, request)
            self.tasks.update(task_id, finished_at=time.time(), result=json.dumps(
                {"summary": summary, "steps": [s.id for s in ordered], "plan_source": plan_source}))
        except TaskCancelled as exc:
            self._finish_cancelled(task_id, str(exc))
        except (JqcError, ProviderUnavailable) as exc:
            self._finish_failed(task_id, str(exc), request)
        except Exception as exc:  # defensively never crash the loop
            log.exception("task %s crashed", task_id)
            self._finish_failed(task_id, f"{type(exc).__name__}: {exc}", request)
        finally:
            self._cancel_events.pop(task_id, None)
            fut = self._runs.pop(task_id, None)
            if fut and not fut.done():
                fut.set_result(self.tasks.get(task_id) or {})

    async def _run_step(self, task_id: str, index: int, step: Any, params: dict,
                        workspace: str, cancel_event: asyncio.Event) -> dict:

        if cancel_event.is_set():
            raise TaskCancelled("Task cancelled by user.")
        resource = _resolve_resource(step.tool, step.action, params)
        decision = self.permissions.check(step.tool, step.action, resource=resource, task_id=task_id)
        if not decision.allowed:
            raise PermissionDenied(decision.reason or f"Action {step.tool}.{step.action} not permitted.")

        self._emit_step(task_id, index, step, EventStatus.started, f"{step.description or step.action}")
        if decision.needs_approval:
            await self._request_approval_and_wait(task_id, step, resource, decision.risk)

        skill = self.registry.get(step.tool)
        ctx = SkillContext(
            task_id=task_id,
            workspace=workspace,
            data_dir=self.settings.data_dir,
            workspace_dir=self.settings.workspace_dir,
            permissions=self.permissions,
            approvals=self.approvals,
            secrets=self.secrets,
            emit=lambda e: (self.bus.publish(e), self.history.append(e)),
            cancel_event=cancel_event,
            demo_mode=self.settings.demo_mode,
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                evidence = await skill.run(step.action, params, ctx)
                check_strict(step.tool, step.action, params, evidence)
                self.activity.record(task_id=task_id, skill=step.tool, action=step.action,
                                     resource=resource, status="completed", outcome="verified")
                self._emit_step(task_id, index, step, EventStatus.completed,
                                message=f"{step.description or step.action} — verified",
                                evidence=evidence)
                return evidence
            except TaskCancelled:
                raise
            except VerificationFailed as exc:
                self._emit_step(task_id, index, step, EventStatus.failed, message=str(exc))
                raise
            except (JqcError, ProviderUnavailable) as exc:
                last_error = exc
                if attempt < 2 and _retryable(exc):
                    await asyncio.sleep(0.5 * (attempt + 1))
                    self._emit_step(task_id, index, step, EventStatus.running,
                                    message=f"Retrying ({attempt + 1}/2): {exc}")
                    continue
                self.activity.record(task_id=task_id, skill=step.tool, action=step.action,
                                     resource=resource, status="failed", outcome=str(exc)[:200])
                self._emit_step(task_id, index, step, EventStatus.failed, message=str(exc))
                self.steps.finish(task_id, index, EventStatus.failed.value, {}, str(exc))
                raise
        raise last_error if last_error else JqcError(f"{step.tool}.{step.action} failed.")

    async def _request_approval_and_wait(self, task_id: str, step: Any, resource: str | None, risk: str) -> None:
        approval_id = self.approvals.request(
            task_id=task_id, action=f"{step.tool}.{step.action}",
            reason=f"{risk} risk step requires your approval: {step.description}",
            resource=resource, risk=risk)
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._approval_futures[approval_id] = fut
        self.tasks.set_status(task_id, TaskStatus.waiting_approval)
        self._emit(Event(
            task_id=task_id, event_type=EventType.approval, status=EventStatus.pending_approval,
            tool=step.tool, action=step.action,
            message=f"Approval needed ({risk} risk): {step.description}",
            evidence={"approval_id": approval_id, "risk": risk, "resource": resource or ""}))
        try:
            decision: ApprovalDecision = await asyncio.wait_for(fut, timeout=1800)
        except TimeoutError:
            self.approvals_repo.decide(approval_id, False, "Timed out")
            raise PermissionDenied("Approval request timed out.") from None
        finally:
            self._approval_futures.pop(approval_id, None)
        if not decision.approve:
            raise PermissionDenied("User denied this step.")
        self.tasks.set_status(task_id, TaskStatus.running)

    def _persist_plan(self, task_id: str, plan: Plan) -> None:
        for i, step in enumerate(plan.steps):
            self.steps.add(task_id, i, step.tool, step.action, step.params,
                           "pending")

    def _emit(self, event: Event) -> None:
        self.bus.publish(event)
        self.history.append(event)
        self.eventlog.append(event)

    def _emit_step(self, task_id: str, index: int, step: Any, status: EventStatus,
                   message: str | None = None, evidence: dict | None = None) -> None:
        ev = Event(task_id=task_id, event_type=EventType.step, status=status,
                   tool=step.tool, action=step.action, message=message,
                   evidence=evidence or {}, step_id=step.id)
        self._emit(ev)

    def _finish_and_report(self, task_id: str, summary: str, outputs: dict, plan: Plan, request: str) -> None:
        report = {
            "summary": summary,
            "steps": [
                {"id": s.id, "tool": s.tool, "action": s.action,
                 "description": s.description, "evidence": outputs.get(s.id)}
                for s in plan.steps
            ],
        }
        self.tasks.update(task_id, result=json.dumps(report, default=str))
        self.activity.record(task_id=task_id, skill=None, action="task.complete",
                             resource=None, status="completed", outcome="verified")
        self._emit(Event(task_id=task_id, event_type=EventType.task, status=EventStatus.completed,
                         message=summary, evidence={"source": "heuristic" if not outputs else "steps"}))
        conv = self.tasks.get(task_id)
        if conv and conv.get("conversation_id"):
            self.conversations.add_message(conv["conversation_id"], "assistant",
                                           summary, task_id=task_id)

    def _finish_failed(self, task_id: str, error: str, request: str) -> None:
        log.warning("task %s failed: %s", task_id, redacted_str(error))
        self.tasks.set_status(task_id, TaskStatus.failed)
        self.tasks.update(task_id, error=error, finished_at=time.time())
        self.activity.record(task_id=task_id, skill=None, action="task.failed",
                             resource=None, status="failed", outcome=error[:300])
        self._emit(Event(task_id=task_id, event_type=EventType.task, status=EventStatus.failed,
                         message=error))

    def _finish_cancelled(self, task_id: str, reason: str) -> None:
        self.tasks.set_status(task_id, TaskStatus.cancelled)
        self.tasks.update(task_id, error=reason, finished_at=time.time())
        self.activity.record(task_id=task_id, skill=None, action="task.cancelled",
                             resource=None, status="cancelled", outcome=reason)
        self._emit(Event(task_id=task_id, event_type=EventType.task, status=EventStatus.cancelled,
                         message=reason))


def _template_params(params: dict, outputs: dict[str, dict]) -> dict:
    def sub(value: Any) -> Any:
        if isinstance(value, str):
            def repl(m: __import__("re").Match) -> str:
                step_id, field = m.group(1), m.group(2)
                out = outputs.get(step_id) or {}
                if field:
                    val = out.get(field)
                    return str(val) if val is not None else m.group(0)
                return str(out) if out else m.group(0)

            return TEMPLATE_RE.sub(repl, value)
        if isinstance(value, dict):
            return {k: sub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [sub(v) for v in value]
        return value

    return sub(params)


def _retryable(exc: Exception) -> bool:
    return isinstance(exc, (ProviderUnavailable, JqcError)) and "timeout" in str(exc).lower()


def _topo(plan: Plan) -> list[Any]:
    """Return steps in a valid topological order (serial execution)."""
    ids = {s.id for s in plan.steps}
    for s in plan.steps:
        for dep in s.depends_on:
            if dep not in ids:
                raise JqcError(f"Step '{s.id}' depends on unknown step '{dep}'")
    result: list[Any] = []
    done: set[str] = set()
    remaining = list(plan.steps)
    while remaining:
        progressed = False
        for s in list(remaining):
            if all(d in done for d in s.depends_on):
                result.append(s)
                done.add(s.id)
                remaining.remove(s)
                progressed = True
        if not progressed:
            raise JqcError("Plan contains a dependency cycle.")
    return result
