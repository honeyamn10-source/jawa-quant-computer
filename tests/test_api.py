"""API server tests using FastAPI's TestClient (loopback, no real bind)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def settings(tmp_path_factory):
    from jqc.config import Settings

    tmp = tmp_path_factory.mktemp("api")
    return Settings(
        data_dir=tmp / "data",
        workspace_dir=tmp / "workspace",
        demo_mode=True,
        browser_headless=True,
    )


@pytest.fixture(scope="module")
def app(settings):
    from jqc.api.server import create_app

    return create_app(settings)


@pytest.fixture(scope="module")
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def live_port(app):
    """Serve the same app on an ephemeral port so the SSE stream (which never
    ends) can be probed with a real HTTP client instead of TestClient."""
    import socket
    import threading
    import time

    import uvicorn

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(cfg)
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return port
        except OSError:
            time.sleep(0.1)
    server.should_exit = True
    raise RuntimeError("live server did not start")


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["version"] == "0.1.0"


def test_skills_manifest(client):
    r = client.get("/api/skills")
    assert r.status_code == 200
    tools = r.json()["tools"]
    names = {t["name"] for t in tools}
    assert "filesystem.write" in names
    assert "browser.open" in names
    assert "shell.run" in names
    assert "scheduler.create" in names


def test_chat_endpoint_creates_task(client):
    r = client.post("/api/chat", json={"message": (
        "Open example.com, capture the page title and save it into a text file "
        "in my workspace.")})
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    assert task_id
    # poll until done
    import time

    for _ in range(50):
        tr = client.get(f"/api/tasks/{task_id}").json()
        if tr["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.1)
    assert tr["status"] == "completed"
    assert len(tr["steps"]) == 3


def test_files_endpoint(client):
    r = client.get("/api/files")
    assert r.status_code == 200
    assert "entries" in r.json()


def test_memory_crud(client):
    r = client.post("/api/memory", json={"content": "remember me", "kind": "preference"})
    assert r.status_code == 200
    items = client.get("/api/memory").json()
    assert any(m["content"] == "remember me" for m in items)


def test_permissions_endpoints(client):
    r = client.post("/api/permissions",
                    json={"risk": "high", "pattern": "*", "policy": "deny", "note": "test"})
    assert r.status_code == 200
    assert any(p["policy"] == "deny" for p in r.json())
    client.delete("/api/permissions")


def test_jobs_crud(client):
    r = client.post("/api/jobs", json={
        "name": "test job", "prompt": "list files", "schedule_type": "interval",
        "trigger": {"every": "30 minutes"}, "workspace": "default"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    jobs = client.get("/api/jobs").json()
    assert any(j["id"] == job_id for j in jobs)
    r = client.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 200


def test_events_endpoint(live_port):
    # Probe the never-ending SSE stream with a real client + short read timeout.
    async def probe():
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(6)) as c,
            c.stream("GET", f"http://127.0.0.1:{live_port}/api/events/stream") as r,
        ):
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]
            lines = []
            async for line in r.aiter_lines():
                lines.append(line)
                if len(lines) >= 2:
                    break
            return lines

    import asyncio

    lines = asyncio.run(probe())
    assert lines and lines[0] == "retry: 1500"


def test_ui_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Jawa Quant Computer" in r.text
    r2 = client.get("/ui/app.js")
    assert r2.status_code == 200


def test_provider_endpoints(client):
    r = client.get("/api/providers")
    assert r.status_code == 200
    # adding an invalid provider must be rejected, not silently saved
    bad = client.post("/api/providers",
                      json={"kind": "openai-compatible", "name": "bad",
                            "base_url": "not-a-url", "model": "m"})
    assert bad.status_code in {422, 400}
