"""Tests for the Tier-4 encrypted-file backend.

Uses tiny Argon2id parameters (8 KiB / 1 iteration / 1 lane) so the
suite runs quickly. The envelope module records what was used, so
production envelopes (64 MiB / 3 iterations / 4 lanes) decrypt
without any test-side coordination.
"""

from __future__ import annotations

import stat
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from kaos_core.config.storage import (
    EncryptedFileStorage,
    StorageTier,
)
from kaos_core.config.storage.envelope import KdfParams

_TEST_KDF = KdfParams.fresh(memory_cost_kib=8, iterations=1, lanes=1)


def _provider(passphrase: str | None) -> Callable[[], str | None]:
    """Return a callable that yields *passphrase* on every call."""

    def _p() -> str | None:
        return passphrase

    return _p


@pytest.fixture
def storage(tmp_path: Path) -> EncryptedFileStorage:
    return EncryptedFileStorage(
        path=tmp_path / "creds.enc",
        passphrase_provider=_provider("test-passphrase"),
        kdf_params=_TEST_KDF,
    )


# ──────────────── tier metadata + probe ────────────────


def test_tier_is_encrypted_file() -> None:
    assert EncryptedFileStorage.tier is StorageTier.ENCRYPTED_FILE


def test_is_available_with_passphrase(tmp_path: Path) -> None:
    s = EncryptedFileStorage(
        path=tmp_path / "creds.enc",
        passphrase_provider=_provider("pp"),
        kdf_params=_TEST_KDF,
    )
    assert s.is_available() is True


def test_is_unavailable_without_passphrase(tmp_path: Path) -> None:
    s = EncryptedFileStorage(
        path=tmp_path / "creds.enc",
        passphrase_provider=_provider(None),
        kdf_params=_TEST_KDF,
    )
    assert s.is_available() is False


def test_env_passphrase_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KAOS_PASSPHRASE", "from-env")
    s = EncryptedFileStorage(path=tmp_path / "creds.enc", kdf_params=_TEST_KDF)
    assert s.is_available() is True
    s.set("kaos-llm", "openai", "default", "v1")
    assert s.get("kaos-llm", "openai", "default") == "v1"


def test_env_provider_strips_blank(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KAOS_PASSPHRASE", "   ")
    s = EncryptedFileStorage(path=tmp_path / "creds.enc", kdf_params=_TEST_KDF)
    assert s.is_available() is False


# ──────────────── round-trip ────────────────


def test_set_get(storage: EncryptedFileStorage) -> None:
    storage.set("kaos-llm", "openai", "default", "sk-test")
    assert storage.get("kaos-llm", "openai", "default") == "sk-test"


def test_get_missing_returns_none(storage: EncryptedFileStorage) -> None:
    assert storage.get("kaos-llm", "openai", "default") is None


def test_overwrite(storage: EncryptedFileStorage) -> None:
    storage.set("kaos-llm", "openai", "default", "v1")
    storage.set("kaos-llm", "openai", "default", "v2")
    assert storage.get("kaos-llm", "openai", "default") == "v2"


def test_delete(storage: EncryptedFileStorage) -> None:
    storage.set("kaos-llm", "openai", "default", "v1")
    storage.delete("kaos-llm", "openai", "default")
    assert storage.get("kaos-llm", "openai", "default") is None


def test_delete_missing_is_silent(storage: EncryptedFileStorage) -> None:
    storage.delete("kaos-llm", "openai", "default")  # no error


def test_list_services(storage: EncryptedFileStorage) -> None:
    storage.set("kaos-llm", "openai", "default", "v1")
    storage.set("kaos-llm", "anthropic", "default", "v2")
    storage.set("kaos-llm", "google", "default", "v3")
    assert storage.list_services("kaos-llm") == ["anthropic", "google", "openai"]


def test_list_services_unknown_module(storage: EncryptedFileStorage) -> None:
    storage.set("kaos-llm", "openai", "default", "v1")
    assert storage.list_services("kaos-source") == []


# ──────────────── persistence + concurrency ────────────────


def test_data_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "creds.enc"
    a = EncryptedFileStorage(path=path, passphrase_provider=_provider("pp"), kdf_params=_TEST_KDF)
    a.set("kaos-llm", "openai", "default", "v1")
    # New instance with the same passphrase should read the same value.
    b = EncryptedFileStorage(path=path, passphrase_provider=_provider("pp"), kdf_params=_TEST_KDF)
    assert b.get("kaos-llm", "openai", "default") == "v1"


def test_wrong_passphrase_raises_runtime_error(tmp_path: Path) -> None:
    path = tmp_path / "creds.enc"
    a = EncryptedFileStorage(
        path=path, passphrase_provider=_provider("right"), kdf_params=_TEST_KDF
    )
    a.set("kaos-llm", "openai", "default", "v1")
    b = EncryptedFileStorage(
        path=path, passphrase_provider=_provider("wrong"), kdf_params=_TEST_KDF
    )
    with pytest.raises(RuntimeError, match="passphrase may be wrong"):
        b.get("kaos-llm", "openai", "default")


def test_existing_file_kdf_is_reused_on_write(tmp_path: Path) -> None:
    """Re-derivation cost is paid once: subsequent writes reuse the
    salt + KDF params from the existing envelope. Without this, every
    write would roll a new salt and force every reader to re-derive.
    """
    from kaos_core.config.storage.envelope import Envelope

    path = tmp_path / "creds.enc"
    a = EncryptedFileStorage(path=path, passphrase_provider=_provider("pp"), kdf_params=_TEST_KDF)
    a.set("kaos-llm", "openai", "default", "v1")
    salt_v1 = Envelope.deserialize(path.read_bytes()).kdf.salt
    a.set("kaos-llm", "anthropic", "default", "v2")
    salt_v2 = Envelope.deserialize(path.read_bytes()).kdf.salt
    assert salt_v1 == salt_v2  # KDF params are sticky across writes


# ──────────────── on-disk hardening ────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits aren't enforced on NTFS")
def test_file_is_owner_only_on_posix(tmp_path: Path) -> None:
    path = tmp_path / "creds.enc"
    s = EncryptedFileStorage(path=path, passphrase_provider=_provider("pp"), kdf_params=_TEST_KDF)
    s.set("kaos-llm", "openai", "default", "v1")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_no_secret_value_in_file(tmp_path: Path) -> None:
    path = tmp_path / "creds.enc"
    s = EncryptedFileStorage(path=path, passphrase_provider=_provider("pp"), kdf_params=_TEST_KDF)
    s.set("kaos-llm", "openai", "default", "VERY-SECRET-VALUE")
    contents = path.read_bytes()
    # Ciphertext is base64; the literal string must not appear.
    assert b"VERY-SECRET-VALUE" not in contents


def test_atomic_write_leaves_no_temp_file(tmp_path: Path) -> None:
    s = EncryptedFileStorage(
        path=tmp_path / "creds.enc",
        passphrase_provider=_provider("pp"),
        kdf_params=_TEST_KDF,
    )
    s.set("kaos-llm", "openai", "default", "v1")
    s.set("kaos-llm", "anthropic", "default", "v2")
    siblings = sorted(p.name for p in tmp_path.iterdir())
    assert siblings == ["creds.enc"], f"unexpected leftover files: {siblings}"
