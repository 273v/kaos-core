"""Agent runtime settings."""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from kaos_core.config.module_settings import ModuleSettings


class AgentSettings(ModuleSettings):
    """Settings for agent task management and polling.

    Env vars use the ``KAOS_AGENT_`` prefix.
    """

    poll_interval: float = 0.25
    """Polling interval (seconds) for task status checks."""

    task_page_size: int = 50
    """Page size for task list pagination."""

    model_config = SettingsConfigDict(
        env_prefix="KAOS_AGENT_",
        env_file=".env",
        extra="ignore",
    )
