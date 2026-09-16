"""Shared fixtures for the test suite. All tests run against a temporary data
directory; no API keys, no real browser, no network required."""

from __future__ import annotations

import pytest
import pytest_asyncio

from jqc.app import build_app
from jqc.config import Settings


@pytest_asyncio.fixture
async def deps(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        workspace_dir=tmp_path / "workspace",
        host="127.0.0.1",
        port=0,
        demo_mode=True,
        approval_mode="prompt",
        browser_headless=True,
    )
    d = build_app(settings, browser_driver="mock")
    yield d
    d["scheduler"]._stop.set()
    d["db"].close()


@pytest.fixture
def ws(deps):
    return deps["settings"].workspace_dir


@pytest.fixture
def agent(deps):
    return deps["agent"]


@pytest.fixture
def router(deps):
    return deps["router"]


@pytest.fixture
def permissions(deps):
    return deps["permissions"]


@pytest.fixture
def secrets(deps):
    return deps["secrets"]
