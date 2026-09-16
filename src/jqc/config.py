"""Application configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATA_DIR = Path.home() / ".jawa-quant-computer"


class Settings(BaseSettings):
    """Runtime settings. Values can come from a .env file or environment variables.

    Never put secrets in this file via .env in the repository; use the secret
    vault (see ``jqc.security.secrets``) for API keys and credentials.
    """

    model_config = SettingsConfigDict(env_prefix="JQC_", env_file=".env", extra="ignore")

    # Runtime
    data_dir: Path = DEFAULT_DATA_DIR
    host: str = "127.0.0.1"
    port: int = 8337
    workspace_dir: Path = Field(default_factory=lambda: DEFAULT_DATA_DIR / "workspace")

    # Privacy mode: local | hybrid | cloud
    privacy_mode: str = "hybrid"

    # Default provider used when the user has not chosen one.
    default_provider: str = "mock"
    default_model: str = "jawa-mock"

    # Resource control
    max_steps_per_task: int = 50
    max_runtime_seconds: int = 1800
    max_concurrent_tasks: int = 4
    browser_headless: bool = True

    # Approvals. In demo mode the mock provider answers locally and permission
    # prompts are auto-resolved for low/medium risk so acceptance flows run.
    approval_mode: str = "prompt"  # prompt | allow-task | deny
    demo_mode: bool = True

    # Secret vault
    vault_file: Path = Field(default_factory=lambda: DEFAULT_DATA_DIR / "secrets.vault")

    # Scheduler
    scheduler_poll_seconds: float = 5.0

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "jqc.sqlite3"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "jqc.log"


settings = Settings()
