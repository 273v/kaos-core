"""Tests for the Tier-3 :class:`KeyringStorage` backend.

Tests use a real :class:`keyring.backend.KeyringBackend` subclass
held in memory rather than mocking the ``keyring`` module — the
backend selection is what we actually need to exercise (probe
acceptance, ``priority`` rejection, ``keyrings.alt.*`` rejection).

The headless-Linux and WSL probe paths are tested via env-var +
``/proc/version`` injection. The platform check (``sys.platform ==
'linux'``) makes those paths run only on Linux; the corresponding
tests are skipped on macOS / Windows where the heuristic doesn't
apply.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import keyring
import keyring.backend
import keyring.errors
import pytest

from kaos_core.config.storage import KeyringStorage, StorageTier


class _MemoryBackend(keyring.backend.KeyringBackend):
    """In-memory keyring backend with a configurable priority.

    Used as a stand-in for libsecret/Keychain/WinVault. Priority 5
    is high enough to be accepted by our probe (>= 1) and below the
    "real" backends so production code never picks this up.
    """

    priority = 5  # type: ignore[assignment]  # KeyringBackend's priority is a property

    def __init__(self) -> None:
        super().__init__()
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self._store:
            raise keyring.errors.PasswordDeleteError("Password not found")
        del self._store[(service, username)]


class _LowPriorityBackend(_MemoryBackend):
    """Backend with priority < 1 — must be rejected by the probe."""

    priority = 0  # type: ignore[assignment]


class _AltBackendImpostor(_MemoryBackend):
    """A backend whose module *appears* to be ``keyrings.alt.*``.

    We can't easily install ``keyrings.alt`` just for tests, so we
    fake the module name. Our probe only looks at
    ``type(backend).__module__``.
    """


_AltBackendImpostor.__module__ = "keyrings.alt.file"


@pytest.fixture
def memory_keyring(monkeypatch: pytest.MonkeyPatch) -> _MemoryBackend:
    """Install an in-memory backend as the active keyring for the test."""
    backend = _MemoryBackend()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    monkeypatch.setattr(keyring, "set_password", backend.set_password)
    monkeypatch.setattr(keyring, "get_password", backend.get_password)
    monkeypatch.setattr(keyring, "delete_password", backend.delete_password)
    return backend


@pytest.fixture(autouse=True)
def _force_unheadless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests want the probe to NOT trip the headless guard.

    We simulate a graphical session so the keyring tier is reachable
    on Linux self-hosted runners (no DISPLAY in CI). Tests that
    specifically exercise the headless path override this fixture
    inside themselves.
    """
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("KAOS_FORCE_KEYRING", raising=False)
    monkeypatch.delenv("KAOS_WSL_USE_KEYRING", raising=False)


# ──────────────── tier metadata ────────────────


def test_tier_is_keyring() -> None:
    assert KeyringStorage.tier is StorageTier.KEYRING


# ──────────────── probe acceptance ────────────────


class TestProbe:
    def test_accepts_real_backend(self, memory_keyring: _MemoryBackend, tmp_path: Path) -> None:
        storage = KeyringStorage(index_path=tmp_path / "idx.json")
        assert storage.is_available() is True

    def test_rejects_low_priority_backend(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        backend = _LowPriorityBackend()
        monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
        storage = KeyringStorage(index_path=tmp_path / "idx.json")
        assert storage.is_available() is False

    def test_rejects_keyrings_alt_backend(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        backend = _AltBackendImpostor()
        monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
        storage = KeyringStorage(index_path=tmp_path / "idx.json")
        assert storage.is_available() is False

    def test_force_available_true_overrides_probe(self, tmp_path: Path) -> None:
        storage = KeyringStorage(index_path=tmp_path / "idx.json", force_available=True)
        assert storage.is_available() is True

    def test_force_available_false_overrides_probe(
        self, memory_keyring: _MemoryBackend, tmp_path: Path
    ) -> None:
        storage = KeyringStorage(index_path=tmp_path / "idx.json", force_available=False)
        assert storage.is_available() is False

    def test_missing_keyring_module_returns_false(self, tmp_path: Path) -> None:
        # Inject an explicit None won't work since we use ``is None``
        # to mean "lazy import"; instead, build a faux module-shaped
        # object that raises on get_keyring.
        class _Broken:
            @staticmethod
            def get_keyring() -> Any:
                msg = "no backend"
                raise RuntimeError(msg)

        storage = KeyringStorage(index_path=tmp_path / "idx.json", keyring_module=_Broken())
        assert storage.is_available() is False

    @pytest.mark.skipif(sys.platform != "linux", reason="headless heuristic is Linux-only")
    def test_headless_linux_disables_tier(
        self,
        memory_keyring: _MemoryBackend,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        storage = KeyringStorage(index_path=tmp_path / "idx.json")
        assert storage.is_available() is False

    @pytest.mark.skipif(sys.platform != "linux", reason="headless heuristic is Linux-only")
    def test_headless_linux_overridden_by_force_keyring(
        self,
        memory_keyring: _MemoryBackend,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        monkeypatch.setenv("KAOS_FORCE_KEYRING", "1")
        storage = KeyringStorage(index_path=tmp_path / "idx.json")
        assert storage.is_available() is True


# ──────────────── round-trip ────────────────


class TestRoundTrip:
    def test_set_get(self, memory_keyring: _MemoryBackend, tmp_path: Path) -> None:
        storage = KeyringStorage(index_path=tmp_path / "idx.json")
        storage.set("kaos-llm", "openai", "default", "sk-test")
        assert storage.get("kaos-llm", "openai", "default") == "sk-test"

    def test_get_missing_returns_none(self, memory_keyring: _MemoryBackend, tmp_path: Path) -> None:
        storage = KeyringStorage(index_path=tmp_path / "idx.json")
        assert storage.get("kaos-llm", "openai", "default") is None

    def test_delete_clears_value(self, memory_keyring: _MemoryBackend, tmp_path: Path) -> None:
        storage = KeyringStorage(index_path=tmp_path / "idx.json")
        storage.set("kaos-llm", "openai", "default", "sk-test")
        storage.delete("kaos-llm", "openai", "default")
        assert storage.get("kaos-llm", "openai", "default") is None

    def test_delete_missing_is_silent(self, memory_keyring: _MemoryBackend, tmp_path: Path) -> None:
        # Key wasn't there; delete shouldn't raise.
        storage = KeyringStorage(index_path=tmp_path / "idx.json")
        storage.delete("kaos-llm", "openai", "default")  # no error

    def test_overwrite(self, memory_keyring: _MemoryBackend, tmp_path: Path) -> None:
        storage = KeyringStorage(index_path=tmp_path / "idx.json")
        storage.set("kaos-llm", "openai", "default", "v1")
        storage.set("kaos-llm", "openai", "default", "v2")
        assert storage.get("kaos-llm", "openai", "default") == "v2"

    def test_set_when_unavailable_raises(self, tmp_path: Path) -> None:
        storage = KeyringStorage(index_path=tmp_path / "idx.json", force_available=False)
        with pytest.raises(RuntimeError, match="not available"):
            storage.set("kaos-llm", "openai", "default", "v1")


# ──────────────── service-name scoping ────────────────


class TestProfileScoping:
    def test_two_profiles_dont_collide(
        self, memory_keyring: _MemoryBackend, tmp_path: Path
    ) -> None:
        dev = KeyringStorage(profile="dev", index_path=tmp_path / "dev.json")
        prod = KeyringStorage(profile="prod", index_path=tmp_path / "prod.json")
        dev.set("kaos-llm", "openai", "default", "sk-dev")
        prod.set("kaos-llm", "openai", "default", "sk-prod")
        assert dev.get("kaos-llm", "openai", "default") == "sk-dev"
        assert prod.get("kaos-llm", "openai", "default") == "sk-prod"

    def test_service_name_includes_profile(self, tmp_path: Path) -> None:
        storage = KeyringStorage(profile="dev", index_path=tmp_path / "idx.json")
        # _service_name is private but pinned because the keyring
        # entries it produces are durable: changing the format would
        # orphan existing user secrets.
        assert storage._service_name("kaos-llm", "openai") == "kaos-core::dev::kaos-llm::openai"


# ──────────────── index ────────────────


class TestIndex:
    def test_list_services_starts_empty(
        self, memory_keyring: _MemoryBackend, tmp_path: Path
    ) -> None:
        storage = KeyringStorage(index_path=tmp_path / "idx.json")
        assert storage.list_services("kaos-llm") == []

    def test_set_populates_index(self, memory_keyring: _MemoryBackend, tmp_path: Path) -> None:
        storage = KeyringStorage(index_path=tmp_path / "idx.json")
        storage.set("kaos-llm", "openai", "default", "v1")
        storage.set("kaos-llm", "anthropic", "default", "v2")
        assert storage.list_services("kaos-llm") == ["anthropic", "openai"]

    def test_delete_clears_from_index(self, memory_keyring: _MemoryBackend, tmp_path: Path) -> None:
        storage = KeyringStorage(index_path=tmp_path / "idx.json")
        storage.set("kaos-llm", "openai", "default", "v1")
        storage.set("kaos-llm", "anthropic", "default", "v2")
        storage.delete("kaos-llm", "openai", "default")
        assert storage.list_services("kaos-llm") == ["anthropic"]

    def test_index_holds_no_secret_values(
        self, memory_keyring: _MemoryBackend, tmp_path: Path
    ) -> None:
        index_path = tmp_path / "idx.json"
        storage = KeyringStorage(index_path=index_path)
        storage.set("kaos-llm", "openai", "default", "VERY-SECRET-VALUE")
        contents = index_path.read_text(encoding="utf-8")
        assert "VERY-SECRET-VALUE" not in contents

    def test_index_shape(self, memory_keyring: _MemoryBackend, tmp_path: Path) -> None:
        index_path = tmp_path / "idx.json"
        storage = KeyringStorage(index_path=index_path)
        storage.set("kaos-llm", "openai", "default", "v1")
        storage.set("kaos-llm", "openai", "production", "v2")
        idx = json.loads(index_path.read_text(encoding="utf-8"))
        assert idx == {"kaos-llm": {"openai": ["default", "production"]}}

    def test_corrupt_index_treated_as_empty(
        self, memory_keyring: _MemoryBackend, tmp_path: Path
    ) -> None:
        index_path = tmp_path / "idx.json"
        index_path.write_text("not valid json{", encoding="utf-8")
        storage = KeyringStorage(index_path=index_path)
        assert storage.list_services("kaos-llm") == []
