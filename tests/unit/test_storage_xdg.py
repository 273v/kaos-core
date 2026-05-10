"""Tests for XDG / Known-Folder path resolution.

Verifies the documented resolution order for each helper:

1. ``KAOS_*_DIR`` env override (tests / containers).
2. Platform-specific base (``%LOCALAPPDATA%`` on Windows, ``$XDG_*_HOME``
   else).
3. Conventional fallback (``~/.config``, ``~/.local/state``,
   ``~/.cache``).

Each test isolates its environment via monkeypatch so the
order-of-precedence is exercised cleanly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from kaos_core.config.storage.xdg import (
    kaos_cache_dir,
    kaos_config_dir,
    kaos_state_dir,
)


@pytest.fixture(autouse=True)
def _clear_xdg_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every XDG / KAOS / LOCALAPPDATA override so tests start clean."""
    for var in (
        "KAOS_CONFIG_DIR",
        "KAOS_STATE_DIR",
        "KAOS_CACHE_DIR",
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
        "LOCALAPPDATA",
    ):
        monkeypatch.delenv(var, raising=False)


class TestExplicitOverrides:
    def test_kaos_config_dir_honors_explicit_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("KAOS_CONFIG_DIR", str(tmp_path / "custom-config"))
        assert kaos_config_dir() == tmp_path / "custom-config"

    def test_kaos_state_dir_honors_explicit_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("KAOS_STATE_DIR", str(tmp_path / "custom-state"))
        assert kaos_state_dir() == tmp_path / "custom-state"

    def test_kaos_cache_dir_honors_explicit_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("KAOS_CACHE_DIR", str(tmp_path / "custom-cache"))
        assert kaos_cache_dir() == tmp_path / "custom-cache"

    def test_empty_override_falls_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Explicitly empty overrides should NOT win — they're noise
        # left by some shells. Falls through to platform default.
        monkeypatch.setenv("KAOS_STATE_DIR", "   ")
        monkeypatch.setenv("XDG_STATE_HOME", "   ")
        # End up with the conventional default (POSIX) or LOCALAPPDATA fallback (Windows).
        result = kaos_state_dir()
        assert "kaos" in result.parts


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX/macOS XDG layout")
class TestXdgPosix:
    def test_state_dir_uses_xdg_state_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        assert kaos_state_dir() == tmp_path / "state" / "kaos"

    def test_state_dir_default_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # No XDG_STATE_HOME → ~/.local/state/kaos
        assert kaos_state_dir() == Path.home() / ".local" / "state" / "kaos"

    def test_config_dir_uses_xdg_config_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        assert kaos_config_dir() == tmp_path / "cfg" / "kaos"

    def test_config_dir_default_fallback(self) -> None:
        assert kaos_config_dir() == Path.home() / ".config" / "kaos"

    def test_cache_dir_uses_xdg_cache_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        assert kaos_cache_dir() == tmp_path / "cache" / "kaos"

    def test_cache_dir_default_fallback(self) -> None:
        assert kaos_cache_dir() == Path.home() / ".cache" / "kaos"

    def test_state_and_config_are_different_locations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Critical: tokens must NOT live in ``~/.config`` because users
        # routinely sync that directory to dotfile repos.
        assert kaos_state_dir() != kaos_config_dir()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows known-folder layout")
class TestXdgWindows:
    def test_state_dir_uses_localappdata(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
        assert kaos_state_dir() == tmp_path / "AppData" / "Local" / "kaos" / "state"

    def test_config_dir_uses_localappdata_not_appdata(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # APPDATA roams; LOCALAPPDATA stays machine-local. Tokens
        # encrypted with DPAPI break under roaming, so all kaos data
        # goes under LOCALAPPDATA.
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))  # decoy
        result = kaos_config_dir()
        assert "Local" in result.parts
        assert "Roaming" not in result.parts

    def test_state_dir_localappdata_fallback(self) -> None:
        # No LOCALAPPDATA → ~/AppData/Local/kaos/state
        assert kaos_state_dir() == Path.home() / "AppData" / "Local" / "kaos" / "state"
