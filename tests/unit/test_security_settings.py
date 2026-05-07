"""Unit tests for kaos_core.security.settings — env var resolution + defaults."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kaos_core.security import KaosSecuritySettings


class TestKaosSecuritySettingsDefaults:
    def test_strict_defaults(self) -> None:
        s = KaosSecuritySettings()
        assert s.block_private_networks is True
        assert s.block_loopback is True
        assert s.block_metadata_services is True
        assert s.allowed_schemes == ("http", "https")
        assert s.allowed_hosts == []
        assert s.response_max_bytes == 100_000_000
        assert s.response_size_check_via_content_length is True
        assert s.response_size_check_via_streaming is True

    def test_response_max_bytes_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            KaosSecuritySettings(response_max_bytes=0)


class TestEnvVarResolution:
    """All knobs flip via KAOS_SECURITY_* env vars. monkeypatch isolates each test."""

    def test_block_private_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAOS_SECURITY_BLOCK_PRIVATE_NETWORKS", "0")
        s = KaosSecuritySettings()
        assert s.block_private_networks is False

    def test_block_loopback_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAOS_SECURITY_BLOCK_LOOPBACK", "0")
        s = KaosSecuritySettings()
        assert s.block_loopback is False

    def test_block_metadata_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAOS_SECURITY_BLOCK_METADATA_SERVICES", "false")
        s = KaosSecuritySettings()
        assert s.block_metadata_services is False

    def test_allowed_hosts_csv_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # pydantic-settings parses lists from JSON or CSV-like strings.
        monkeypatch.setenv(
            "KAOS_SECURITY_ALLOWED_HOSTS",
            '["internal.example.com","10.0.0.0/24"]',
        )
        s = KaosSecuritySettings()
        assert s.allowed_hosts == ["internal.example.com", "10.0.0.0/24"]

    def test_response_max_bytes_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAOS_SECURITY_RESPONSE_MAX_BYTES", "5000000")
        s = KaosSecuritySettings()
        assert s.response_max_bytes == 5_000_000

    def test_explicit_overrides_beat_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAOS_SECURITY_BLOCK_PRIVATE_NETWORKS", "0")
        s = KaosSecuritySettings(block_private_networks=True)
        assert s.block_private_networks is True

    def test_unknown_env_vars_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # extra='ignore' so spurious vars don't crash future deployments.
        monkeypatch.setenv("KAOS_SECURITY_NOT_A_REAL_FIELD", "x")
        # Should not raise.
        KaosSecuritySettings()
