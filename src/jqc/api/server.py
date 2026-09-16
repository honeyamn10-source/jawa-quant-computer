"""Loopback-only FastAPI server: chat, tasks, events (SSE), providers,
permissions, approvals, scheduler jobs, memory, activity and settings.

The server binds 127.0.0.1 by default and must never be exposed to the LAN
without authentication (see docs/security/NETWORK.md).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jqc.app import build_app
from jqc.config import Settings
from jqc.config import settings as default_settings
from jqc.models.router import build_provider
from jqc.storage.repos import Providers as ProvidersRepo

_UI_DIR = Path(__file__).resolve().parent.parent.parent.parent / "ui" / "web"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    workspace: str = "default"
    conversation_id: str | None = None


class ProviderCreate(BaseModel):
    id: str | None = None
    kind: str = "openai-compatible"
    name: str
    base_url: str | None = None
    model: str = ""
    api_key: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ProviderSetDefault(BaseModel):
    model: str


class ApprovalDecisionIn(BaseModel):
    approve: bool
    note: str | None = None


class JobCreate(BaseModel):
    name: str
    prompt: str
    schedule_type: str
    trigger: dict[str, Any]
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    workspace: str = "default"


class PermissionRuleIn(BaseModel):
    risk: str
    pattern: str
    policy: str
    scope: str = "task"
    note: str | None = None


class MemoryIn(BaseModel):
    kind: str = "preference"
    scope: str = "default"
    content: str
    key: str | None = None


class SettingsIn(BaseModel):
    privacy_mode: str | None = None
    approval_mode: str | None = None
    demo_mode: bool | None = None
    browser_headless: bool | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or default_settings
    deps = build_app(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await deps["scheduler"].start()
        yield
        await deps["scheduler"].stop()
        deps["db"].close()

    app = FastAPI(title="Jawa Quant Computer", version="0.1.0", lifespan=lifespan)
    app.state.deps = deps

    def s(section: Any) -> Any:
        return deps[section]

    # ------------------------------------------------------------ health
    @app.get("/api/health")
    async def health():
        provider, model = s("router").default()
        ok, detail = await provider.health()
        return {
            "status": "ok" if ok else "degraded",
            "provider": provider.name,
            "model": model,
            "provider_detail": detail,
            "version": "0.1.0",
            "privacy_mode": settings.privacy_mode,
            "host": settings.host,
            "port": settings.port,
        }

    # --------------------------------------------------------------- chat
    @app.post("/api/chat")
    async def chat(req: ChatRequest):
        agent = s("agent")
        conversation_id = req.conversation_id
        if not conversation_id:
            conversation_id = _conversations(agent).create(req.workspace, req.message[:40])
        resp = agent.submit(req.message, workspace=req.workspace, conversation_id=conversation_id)
        return resp.model_dump()

    @app.get("/api/tasks")
    async def list_tasks(workspace: str | None = None, limit: int = Query(50, le=200)):
        return s("agent").tasks.list(workspace=workspace, limit=limit)

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str):
        task = s("agent").tasks.get(task_id)
        if not task:
            raise HTTPException(404, "task not found")
        task["steps"] = s("agent").steps.for_task(task_id)
        return task

    @app.post("/api/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str):
        await s("agent").cancel(task_id)
        return {"cancelled": True, "task_id": task_id}

    @app.get("/api/tasks/{task_id}/events")
    async def task_events(task_id: str):
        events = s("eventlog").for_task(task_id)
        return events

    # --------------------------------------------------------------- SSE
    @app.get("/api/events/stream")
    async def stream(request: Request):
        bus = s("bus")
        history = s("history")
        queue = bus.subscribe()

        async def gen():
            yield b"retry: 1500\n\n"
            for ev in history.all():
                yield f"data: {json.dumps(ev)}\n\n".encode()
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield b": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(ev.model_dump())}\n\n".encode()
            finally:
                bus.unsubscribe(queue)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ----------------------------------------------------------- activity
    @app.get("/api/activity")
    async def activity(limit: int = Query(200, le=1000)):
        return s("activity").list(limit=limit)

    # ---------------------------------------------------------- providers
    @app.get("/api/providers")
    async def providers():
        rows = s("router").list_providers()
        return [
            {**r, "has_key": bool(s("secrets").get(f"provider.{r['id']}.api_key"))}
            for r in rows
        ]

    @app.post("/api/providers")
    async def add_provider(body: ProviderCreate):
        provider_id = body.id or f"p_{uuid.uuid4().hex[:10]}"
        if body.kind != "mock" and not body.base_url:
            raise HTTPException(422, "base_url is required for this provider kind")
        repo = ProvidersRepo(s("db"))
        try:
            repo.upsert(provider_id, body.kind, body.name, body.base_url, body.model or "", body.config)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if body.api_key:
            s("secrets").set(f"provider.{provider_id}.api_key", body.api_key)
        record = repo.get(provider_id)
        try:
            adapter = build_provider(record, s("secrets"))
        except Exception as exc:
            repo.delete(provider_id)
            raise HTTPException(422, f"invalid provider: {exc}") from exc
        ok, detail, models = await adapter.test_connection(body.api_key or s("secrets").get(
            f"provider.{provider_id}.api_key"))
        return {"id": provider_id, "ok": ok, "detail": detail, "models": models, "record": record}

    @app.post("/api/providers/{provider_id}/test")
    async def test_provider(provider_id: str):
        ok, detail, models = await s("router").test(provider_id)
        return {"ok": ok, "detail": detail, "models": models}

    @app.post("/api/providers/{provider_id}/default")
    async def set_default(provider_id: str, body: ProviderSetDefault):
        repo = ProvidersRepo(s("db"))
        record = repo.get(provider_id)
        if not record:
            raise HTTPException(404, "provider not found")
        repo.set_default(provider_id, body.model)
        return {"default": provider_id, "model": body.model}

    @app.delete("/api/providers/{provider_id}")
    async def delete_provider(provider_id: str):
        s("secrets").delete(f"provider.{provider_id}.api_key")
        ProvidersRepo(s("db")).delete(provider_id)
        return {"deleted": provider_id}

    @app.get("/api/models")
    async def models():
        router = s("router")
        provider, model = router.default()
        return {"default_provider": provider.name, "default_model": model,
                "providers": router.list_providers()}

    # ---------------------------------------------------------- permissions
    @app.get("/api/permissions")
    async def list_permissions():
        return s("permissions").repo.all()

    @app.post("/api/permissions")
    async def add_permission(body: PermissionRuleIn):
        if body.risk not in {"low", "medium", "high"} or body.policy not in {"ask", "allow", "deny"}:
            raise HTTPException(422, "invalid risk or policy")
        s("permissions").repo.add(body.risk, body.pattern, body.policy, body.scope, body.note)
        return s("permissions").repo.all()

    @app.delete("/api/permissions")
    async def clear_permissions():
        s("permissions").repo.clear()
        return {"cleared": True}

    # ------------------------------------------------------------ approvals
    @app.get("/api/approvals")
    async def list_approvals(status: str = "pending"):
        return s("approvals").list(status)

    @app.post("/api/approvals/{approval_id}/decide")
    async def decide(approval_id: str, body: ApprovalDecisionIn):
        row = s("agent").decide(approval_id, body.approve, body.note)
        if not row:
            raise HTTPException(404, "approval not found")
        return row

    # --------------------------------------------------------------- acting
    @app.get("/api/acting")
    async def acting():
        return {"active": [tid for tid in s("agent")._runs]}

    # -------------------------------------------------------------- jobs
    @app.get("/api/jobs")
    async def list_jobs():
        return s("scheduler").repo.list()

    @app.post("/api/jobs")
    async def create_job(body: JobCreate):
        from jqc.scheduler.times import compute_next, resolve_tz

        if body.schedule_type not in {"once", "interval", "cron"}:
            raise HTTPException(422, "invalid schedule_type")
        trigger = body.trigger
        if trigger.get("timezone"):
            resolve_tz(trigger.get("timezone"))
        nxt = compute_next(body.schedule_type, trigger)
        jid = s("scheduler").repo.create(body.workspace, body.name, body.prompt,
                                         body.schedule_type, trigger, body.retry_policy)
        s("scheduler").repo.update(jid, next_run_at=nxt.timestamp())
        return {"job_id": jid, "next_run_at": nxt.isoformat()}

    @app.post("/api/jobs/{job_id}/toggle")
    async def toggle_job(job_id: str, enabled: bool = Query(True)):
        job = s("scheduler").repo.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        s("scheduler").repo.update(job_id, enabled=1 if enabled else 0)
        if enabled and not job.get("next_run_at"):
            from jqc.scheduler.times import compute_next

            nxt = compute_next(job["schedule_type"], job.get("trigger") or {})
            s("scheduler").repo.update(job_id, next_run_at=nxt.timestamp(), status="idle")
        return {"job_id": job_id, "enabled": enabled}

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        job = s("scheduler").repo.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        s("scheduler").repo.update(job_id, enabled=0, status="cancelled")
        return {"job_id": job_id, "status": "cancelled"}

    # ---------------------------------------------------------- memory
    @app.get("/api/memory")
    async def list_memory(kind: str | None = None, scope: str | None = None):
        from jqc.storage.repos import Memories

        return Memories(s("db")).list(kind=kind, scope=scope)

    @app.post("/api/memory")
    async def save_memory(body: MemoryIn):
        from jqc.storage.repos import Memories

        Memories(s("db")).save(body.kind, body.scope, body.content, body.key)
        return {"saved": True}

    @app.delete("/api/memory/{memory_id}")
    async def delete_memory(memory_id: int):
        from jqc.storage.repos import Memories

        Memories(s("db")).delete(memory_id)
        return {"deleted": memory_id}

    # ------------------------------------------------------------- settings
    @app.get("/api/settings")
    async def get_settings():
        return {"privacy_mode": settings.privacy_mode, "approval_mode": settings.approval_mode,
                "demo_mode": settings.demo_mode, "browser_headless": settings.browser_headless,
                "data_dir": str(settings.data_dir), "workspace_dir": str(settings.workspace_dir),
                "port": settings.port, "host": settings.host}

    @app.post("/api/settings")
    async def update_settings(body: SettingsIn):
        if body.privacy_mode in {"local", "hybrid", "cloud"}:
            settings.privacy_mode = body.privacy_mode
        if body.approval_mode in {"prompt", "allow-task", "deny"}:
            settings.approval_mode = body.approval_mode
        if body.demo_mode is not None:
            settings.demo_mode = body.demo_mode
        if body.browser_headless is not None:
            settings.browser_headless = body.browser_headless
        return await get_settings()

    # -------------------------------------------------------------- files
    @app.get("/api/files")
    async def list_files(path: str = "."):
        from jqc.skills.filesystem import _resolve

        base = _resolve(settings.workspace_dir, path)
        if not base.exists() or not base.is_dir():
            raise HTTPException(404, "directory not found")
        entries = []
        for e in sorted(base.iterdir(), key=lambda x: x.name):
            entries.append({"name": e.name, "is_dir": e.is_dir(), "path": str(e.relative_to(settings.workspace_dir))})
        return {"path": str(base), "entries": entries}

    # ------------------------------------------------------------ computer
    @app.get("/api/computer")
    async def computer_info():
        from jqc.skills.base import SkillContext
        from jqc.skills.computer import ComputerSkill

        skill = ComputerSkill()
        ctx = SkillContext(
            task_id="api.inspect", workspace="default",
            data_dir=settings.data_dir, workspace_dir=settings.workspace_dir,
            permissions=s("permissions"), approvals=s("approvals"), secrets=s("secrets"),
            demo_mode=settings.demo_mode,
        )
        return await skill.run("info", {}, ctx)

    @app.get("/api/skills")
    async def skills():
        return {
            "tools": [
                {"name": t.name, "description": t.description,
                 "parameters": t.parameters, "risk": t.risk}
                for t in s("registry").tools()
            ],
            "names": s("registry").names(),
        }

    # ------------------------------------------------------------ browser
    @app.get("/api/browser/health")
    async def browser_health():
        skill = s("registry").get("browser")
        ok, detail = await skill.controller.health()
        return {"ok": ok, "detail": detail, "driver": skill.controller.__class__.__name__}

    # ------------------------------------------------------------ static UI
    _mount_static(app, settings)

    @app.get("/")
    async def index():
        return FileResponse(_UI_DIR / "index.html")

    return app


def _mount_static(app: FastAPI, settings: Settings) -> None:
    if _UI_DIR.exists():
        app.mount("/ui", StaticFiles(directory=str(_UI_DIR)), name="ui")


def _conversations(agent: Any):
    return agent.conversations


def run(host: str | None = None, port: int | None = None) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=host or default_settings.host, port=port or default_settings.port)


app = create_app()
