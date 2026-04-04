"""Tests for ModuleSettings base class."""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from kaos_core.base.context import KaosContext
from kaos_core.config.module_settings import ModuleSettings


class SampleSettings(ModuleSettings):
    """Test settings subclass."""

    timeout: float = 30.0
    retries: int = 3
    api_key: SecretStr | None = None
    mode: Literal["fast", "safe"] = "safe"

    model_config = SettingsConfigDict(
        env_prefix="KAOS_SAMPLE_",
        extra="ignore",
    )


class TestModuleSettingsDefaults:
    def test_defaults(self) -> None:
        s = SampleSettings()
        assert s.timeout == 30.0
        assert s.retries == 3
        assert s.api_key is None
        assert s.mode == "safe"

    def test_explicit_override(self) -> None:
        s = SampleSettings(timeout=10.0, retries=1)
        assert s.timeout == 10.0
        assert s.retries == 1


class TestModuleSettingsFromEnv:
    def test_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAOS_SAMPLE_TIMEOUT", "5.0")
        monkeypatch.setenv("KAOS_SAMPLE_RETRIES", "1")
        monkeypatch.setenv("KAOS_SAMPLE_MODE", "fast")
        s = SampleSettings()
        assert s.timeout == 5.0
        assert s.retries == 1
        assert s.mode == "fast"

    def test_secret_str_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAOS_SAMPLE_API_KEY", "sk-secret-123")
        s = SampleSettings()
        assert s.api_key is not None
        assert s.api_key.get_secret_value() == "sk-secret-123"
        # SecretStr masks in repr
        assert "sk-secret-123" not in repr(s.api_key)


class TestModuleSettingsFromContext:
    def test_from_context_none(self) -> None:
        s = SampleSettings.from_context(None)
        assert s.timeout == 30.0

    def test_from_context_overrides(self) -> None:
        ctx = KaosContext.create_test_context()
        ctx.set_config("timeout", 5.0)
        ctx.set_config("mode", "fast")
        s = SampleSettings.from_context(ctx)
        assert s.timeout == 5.0
        assert s.mode == "fast"
        # Non-overridden fields keep defaults
        assert s.retries == 3

    def test_from_context_with_explicit_overrides(self) -> None:
        ctx = KaosContext.create_test_context()
        ctx.set_config("timeout", 5.0)
        # Explicit overrides beat context
        s = SampleSettings.from_context(ctx, timeout=1.0)
        assert s.timeout == 1.0

    def test_from_context_ignores_unknown_keys(self) -> None:
        ctx = KaosContext.create_test_context()
        ctx.set_config("unknown_key", "value")
        # Should not raise
        s = SampleSettings.from_context(ctx)
        assert s.timeout == 30.0

    def test_env_plus_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAOS_SAMPLE_TIMEOUT", "10.0")
        ctx = KaosContext.create_test_context()
        ctx.set_config("retries", 1)
        s = SampleSettings.from_context(ctx)
        # Env sets timeout, context sets retries
        assert s.timeout == 10.0
        assert s.retries == 1

    def test_context_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAOS_SAMPLE_TIMEOUT", "10.0")
        ctx = KaosContext.create_test_context()
        ctx.set_config("timeout", 2.0)
        s = SampleSettings.from_context(ctx)
        # Context wins over env
        assert s.timeout == 2.0


class TestKaosContextGetModuleSettings:
    def test_get_module_settings(self) -> None:
        ctx = KaosContext.create_test_context()
        ctx.set_config("timeout", 7.5)
        s = ctx.get_module_settings(SampleSettings)
        assert s.timeout == 7.5
        assert s.retries == 3

    def test_get_module_settings_no_overrides(self) -> None:
        ctx = KaosContext.create_test_context()
        s = ctx.get_module_settings(SampleSettings)
        assert s.timeout == 30.0
