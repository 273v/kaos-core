"""Tests for the Tier 5 plaintext adapter.

:class:`PlaintextStorage` wraps a :class:`CredentialStore` to
implement the :class:`SecretStorage` Protocol. The underlying
hardening contract (mode 0o600 on POSIX, NTFS DACL on Windows) is
covered by ``test_credentials.py``; here we only verify the adapter
correctly forwards calls and reports tier metadata.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos_core.config.credentials import CredentialStore
from kaos_core.config.storage import PlaintextStorage, StorageTier


def test_tier_is_plaintext() -> None:
    assert PlaintextStorage.tier is StorageTier.PLAINTEXT


def test_is_available_is_always_true(tmp_path: Path) -> None:
    # The plaintext tier is the floor; even when the parent dir
    # doesn't exist yet (CredentialStore mkdirs on first write), the
    # adapter reports available.
    storage = PlaintextStorage(path=tmp_path / "nested" / "subdir" / "creds.json")
    assert storage.is_available() is True


def test_set_get_round_trip(tmp_path: Path) -> None:
    storage = PlaintextStorage(path=tmp_path / "creds.json")
    storage.set("kaos-llm", "openai", "default", "sk-test")
    assert storage.get("kaos-llm", "openai", "default") == "sk-test"


def test_get_missing_returns_none(tmp_path: Path) -> None:
    storage = PlaintextStorage(path=tmp_path / "creds.json")
    assert storage.get("kaos-llm", "openai", "default") is None


def test_delete_removes_secret(tmp_path: Path) -> None:
    storage = PlaintextStorage(path=tmp_path / "creds.json")
    storage.set("kaos-llm", "openai", "default", "sk-test")
    storage.delete("kaos-llm", "openai", "default")
    assert storage.get("kaos-llm", "openai", "default") is None


def test_list_services_returns_sorted(tmp_path: Path) -> None:
    storage = PlaintextStorage(path=tmp_path / "creds.json")
    storage.set("kaos-llm", "openai", "default", "v1")
    storage.set("kaos-llm", "anthropic", "default", "v2")
    storage.set("kaos-llm", "google", "default", "v3")
    assert storage.list_services("kaos-llm") == ["anthropic", "google", "openai"]


def test_list_services_for_unknown_module_is_empty(tmp_path: Path) -> None:
    storage = PlaintextStorage(path=tmp_path / "creds.json")
    storage.set("kaos-llm", "openai", "default", "v1")
    assert storage.list_services("kaos-source") == []


def test_explicit_store_arg(tmp_path: Path) -> None:
    """Caller can supply a pre-built CredentialStore."""
    inner = CredentialStore(tmp_path / "preset.json")
    inner.set("kaos-llm", "openai", "default", "preset-value")
    storage = PlaintextStorage(store=inner)
    assert storage.get("kaos-llm", "openai", "default") == "preset-value"
    assert storage.store is inner


def test_rejects_both_store_and_path(tmp_path: Path) -> None:
    inner = CredentialStore(tmp_path / "x.json")
    with pytest.raises(ValueError, match=r"store=.*path="):
        PlaintextStorage(store=inner, path=tmp_path / "y.json")
