"""Dependency container wiring settings, storage, security, models and skills."""

from __future__ import annotations

import logging
from pathlib import Path

from jqc.config import Settings
from jqc.models.router import ModelRouter
from jqc.orchestrator.agent import AgentService
from jqc.orchestrator.events import EventBus, EventHistory
from jqc.scheduler.service import SchedulerService
from jqc.security.permissions import ApprovalService, PermissionManager
from jqc.security.secrets import RedactingFormatter, SecretStore
from jqc.skills.base import SkillRegistry
from jqc.skills.browser import BrowserSkill
from jqc.skills.computer import ComputerSkill
from jqc.skills.documents import DocumentsSkill
from jqc.skills.filesystem import FilesystemSkill
from jqc.skills.git import GitSkill
from jqc.skills.memory import MemorySkill
from jqc.skills.research import ResearchSkill
from jqc.skills.scheduler import SchedulerSkill
from jqc.skills.search import SearchSkill
from jqc.skills.shell import ShellSkill
from jqc.storage.db import Database
from jqc.storage.repos import make_defaults


def build_app(settings: Settings, browser_driver: str | None = None) -> dict:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)

    _configure_logging(settings.log_path)

    db = Database(settings.sqlite_path)
    make_defaults(db)
    secrets = SecretStore(settings.vault_file)

    registry = SkillRegistry()
    registry.register(FilesystemSkill())
    registry.register(ShellSkill())
    registry.register(GitSkill())
    registry.register(BrowserSkill(settings.data_dir, headless=settings.browser_headless,
                                   driver=browser_driver))
    registry.register(DocumentsSkill())
    registry.register(MemorySkill(db))
    registry.register(SearchSkill())
    registry.register(ResearchSkill())
    registry.register(ComputerSkill())
    registry.register(SchedulerSkill(db))

    router = ModelRouter(db, secrets)
    permissions = PermissionManager(db, settings.approval_mode, settings.demo_mode)
    approvals = ApprovalService(db)
    bus = EventBus()
    history = EventHistory()
    agent = AgentService(settings, db, secrets, registry, router, permissions, approvals, bus, history)
    scheduler = SchedulerService(settings, db, agent)

    return {
        "settings": settings,
        "db": db,
        "secrets": secrets,
        "registry": registry,
        "router": router,
        "permissions": permissions,
        "approvals": approvals,
        "bus": bus,
        "history": history,
        "agent": agent,
        "scheduler": scheduler,
    }


def _configure_logging(log_path: Path) -> None:
    handlers: list[logging.Handler] = []
    try:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handlers.append(fh)
    except OSError:
        pass
    sh = logging.StreamHandler()
    sh.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handlers.append(sh)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
