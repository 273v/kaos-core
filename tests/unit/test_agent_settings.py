"""Tests for AgentSettings."""

from __future__ import annotations

import pytest

from kaos_core.mcp_types.settings import AgentSettings
from kaos_core.mcp_types.task import TaskManager


class TestAgentSettingsDefaults:
    def test_defaults(self) -> None:
        s = AgentSettings()
        assert s.poll_interval == 0.25
        assert s.task_page_size == 50

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAOS_AGENT_POLL_INTERVAL", "0.5")
        monkeypatch.setenv("KAOS_AGENT_TASK_PAGE_SIZE", "100")
        s = AgentSettings()
        assert s.poll_interval == 0.5
        assert s.task_page_size == 100


class TestTaskManagerWithSettings:
    def test_default_settings(self) -> None:
        tm = TaskManager(enabled=True)
        assert tm._settings.poll_interval == 0.25
        assert tm._settings.task_page_size == 50

    def test_custom_settings(self) -> None:
        s = AgentSettings(poll_interval=1.0, task_page_size=25)
        tm = TaskManager(enabled=True, settings=s)
        assert tm._settings.poll_interval == 1.0
        assert tm._settings.task_page_size == 25
