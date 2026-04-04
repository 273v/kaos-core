"""Tests for resolve_secret() helper."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from kaos_core.config.credentials import CredentialStore
from kaos_core.config.secrets import resolve_secret


class TestResolveSecret:
    def test_settings_value_wins(self) -> None:
        result = resolve_secret(SecretStr("from-settings"), env_var="NONEXISTENT_VAR")
        assert result == "from-settings"

    def test_env_var_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_API_KEY", "from-env")
        result = resolve_secret(None, env_var="MY_API_KEY")
        assert result == "from-env"

    def test_env_var_empty_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_API_KEY", "")
        result = resolve_secret(None, env_var="MY_API_KEY")
        assert result is None

    def test_credential_store_fallback(self, tmp_path: Path) -> None:
        store = CredentialStore(tmp_path / "creds.json")
        store.set("web", "serpapi", "default", "from-store")
        result = resolve_secret(
            None,
            credential_store=store,
            module="web",
            service="serpapi",
        )
        assert result == "from-store"

    def test_credential_store_missing_returns_none(self, tmp_path: Path) -> None:
        store = CredentialStore(tmp_path / "creds.json")
        result = resolve_secret(
            None,
            credential_store=store,
            module="web",
            service="nonexistent",
        )
        assert result is None

    def test_all_none_returns_none(self) -> None:
        result = resolve_secret(None)
        assert result is None

    def test_priority_settings_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_API_KEY", "from-env")
        result = resolve_secret(SecretStr("from-settings"), env_var="MY_API_KEY")
        assert result == "from-settings"

    def test_priority_env_over_store(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MY_API_KEY", "from-env")
        store = CredentialStore(tmp_path / "creds.json")
        store.set("web", "serpapi", "default", "from-store")
        result = resolve_secret(
            None,
            env_var="MY_API_KEY",
            credential_store=store,
            module="web",
            service="serpapi",
        )
        assert result == "from-env"
