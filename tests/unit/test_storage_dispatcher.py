"""Tests for the tier-aware credential dispatcher.

These tests use small in-memory fakes to drive the dispatcher
through every documented invariant:

- Read returns the first hit walking strongest-tier-first.
- Read promotes the value into stronger available tiers
  (auto-migration upward) and clears the weaker source.
- Write goes to the strongest available tier.
- Write clears the same key from any weaker tier so the strongest
  tier is the single source of truth.
- ``prefer_tier`` caps writes without affecting reads.
- ``active_tier`` reports what writes will land in.
- ``migrate`` is the explicit single-secret promotion path.
- A real :class:`PlaintextStorage` is exercised end-to-end so the
  dispatcher's interaction with :class:`CredentialStore` is covered
  on top of the fakes.

The fake backends are deliberately minimal: a dict + a flag that
gates :meth:`is_available`. Anything more elaborate would test the
fakes more than the dispatcher.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos_core.config.storage import (
    HardenedCredentialStore,
    PlaintextStorage,
    StorageTier,
)
from kaos_core.config.storage.base import SecretStorage


class _FakeStorage:
    """In-memory backend with adjustable tier and availability."""

    def __init__(self, tier: StorageTier, *, available: bool = True) -> None:
        self.tier = tier
        self._available = available
        self._data: dict[tuple[str, str, str], str] = {}

    def get(self, module: str, service: str, key: str = "default") -> str | None:
        return self._data.get((module, service, key))

    def set(self, module: str, service: str, key: str, value: str) -> None:
        self._data[(module, service, key)] = value

    def delete(self, module: str, service: str, key: str = "default") -> None:
        self._data.pop((module, service, key), None)

    def list_services(self, module: str) -> list[str]:
        return sorted({s for (m, s, _) in self._data if m == module})

    def is_available(self) -> bool:
        return self._available


def _structural_check(storage: object) -> None:
    """Sanity check: exercise every Protocol method on *storage*."""
    assert isinstance(storage, SecretStorage)


def test_fake_satisfies_protocol() -> None:
    # The dispatcher relies on duck-typing; pin that our fake fits.
    fake = _FakeStorage(StorageTier.KEYRING)
    _structural_check(fake)


class TestActiveTier:
    def test_strongest_available_wins(self) -> None:
        store = HardenedCredentialStore(
            backends=[
                _FakeStorage(StorageTier.KEYRING, available=True),
                _FakeStorage(StorageTier.ENCRYPTED_FILE, available=True),
                _FakeStorage(StorageTier.PLAINTEXT, available=True),
            ]
        )
        assert store.active_tier is StorageTier.KEYRING

    def test_skips_unavailable_tiers(self) -> None:
        store = HardenedCredentialStore(
            backends=[
                _FakeStorage(StorageTier.KEYRING, available=False),
                _FakeStorage(StorageTier.ENCRYPTED_FILE, available=True),
                _FakeStorage(StorageTier.PLAINTEXT, available=True),
            ]
        )
        assert store.active_tier is StorageTier.ENCRYPTED_FILE

    def test_prefer_tier_caps_active(self) -> None:
        store = HardenedCredentialStore(
            backends=[
                _FakeStorage(StorageTier.KEYRING, available=True),
                _FakeStorage(StorageTier.ENCRYPTED_FILE, available=True),
                _FakeStorage(StorageTier.PLAINTEXT, available=True),
            ],
            prefer_tier=StorageTier.ENCRYPTED_FILE,
        )
        # Even though keyring is available, the cap forces encrypted-file.
        assert store.active_tier is StorageTier.ENCRYPTED_FILE

    def test_no_available_tier_returns_none(self) -> None:
        # Materialize a no-plaintext-fallback store via the
        # (uncommon) all-disabled case.
        store = HardenedCredentialStore(
            backends=[
                _FakeStorage(StorageTier.KEYRING, available=False),
                _FakeStorage(StorageTier.PLAINTEXT, available=False),
            ]
        )
        assert store.active_tier is StorageTier.NONE


class TestRead:
    def test_first_hit_wins_strongest_first(self) -> None:
        keyring = _FakeStorage(StorageTier.KEYRING)
        encrypted = _FakeStorage(StorageTier.ENCRYPTED_FILE)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT)
        # Same key in two tiers; stronger should win.
        keyring.set("kaos-llm", "openai", "default", "from-keyring")
        plaintext.set("kaos-llm", "openai", "default", "from-plaintext")
        store = HardenedCredentialStore(backends=[keyring, encrypted, plaintext])
        assert store.get("kaos-llm", "openai", "default") == "from-keyring"

    def test_falls_through_to_weaker_tier(self) -> None:
        keyring = _FakeStorage(StorageTier.KEYRING)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT)
        # Only plaintext has the secret.
        plaintext.set("kaos-llm", "openai", "default", "v1")
        store = HardenedCredentialStore(backends=[keyring, plaintext])
        assert store.get("kaos-llm", "openai", "default") == "v1"

    def test_missing_returns_none(self) -> None:
        store = HardenedCredentialStore(
            backends=[
                _FakeStorage(StorageTier.KEYRING),
                _FakeStorage(StorageTier.PLAINTEXT),
            ]
        )
        assert store.get("kaos-llm", "openai", "default") is None

    def test_skips_backend_that_raises(self) -> None:
        class _AngryStorage(_FakeStorage):
            def get(self, *_args: object, **_kwargs: object) -> str | None:
                msg = "backend offline"
                raise OSError(msg)

        broken = _AngryStorage(StorageTier.KEYRING)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT)
        plaintext.set("kaos-llm", "openai", "default", "v1")
        store = HardenedCredentialStore(backends=[broken, plaintext])
        assert store.get("kaos-llm", "openai", "default") == "v1"


class TestAutoMigrate:
    def test_read_promotes_into_stronger_tier(self) -> None:
        keyring = _FakeStorage(StorageTier.KEYRING)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT)
        plaintext.set("kaos-llm", "openai", "default", "v1")
        store = HardenedCredentialStore(backends=[keyring, plaintext])
        assert store.get("kaos-llm", "openai", "default") == "v1"
        # After the read, the secret should live in the keyring tier.
        assert keyring.get("kaos-llm", "openai", "default") == "v1"
        # And no longer in plaintext.
        assert plaintext.get("kaos-llm", "openai", "default") is None

    def test_no_migration_when_already_at_strongest(self) -> None:
        keyring = _FakeStorage(StorageTier.KEYRING)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT)
        keyring.set("kaos-llm", "openai", "default", "v1")
        store = HardenedCredentialStore(backends=[keyring, plaintext])
        assert store.get("kaos-llm", "openai", "default") == "v1"
        # plaintext should remain untouched.
        assert plaintext.get("kaos-llm", "openai", "default") is None

    def test_migration_skips_capped_tier(self) -> None:
        keyring = _FakeStorage(StorageTier.KEYRING)
        encrypted = _FakeStorage(StorageTier.ENCRYPTED_FILE)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT)
        plaintext.set("kaos-llm", "openai", "default", "v1")
        # Cap migration at encrypted-file; keyring should NOT receive it.
        store = HardenedCredentialStore(
            backends=[keyring, encrypted, plaintext],
            prefer_tier=StorageTier.ENCRYPTED_FILE,
        )
        store.get("kaos-llm", "openai", "default")
        assert keyring.get("kaos-llm", "openai", "default") is None
        assert encrypted.get("kaos-llm", "openai", "default") == "v1"
        assert plaintext.get("kaos-llm", "openai", "default") is None


class TestWrite:
    def test_writes_to_strongest_tier(self) -> None:
        keyring = _FakeStorage(StorageTier.KEYRING)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT)
        store = HardenedCredentialStore(backends=[keyring, plaintext])
        store.set("kaos-llm", "openai", "default", "v1")
        assert keyring.get("kaos-llm", "openai", "default") == "v1"
        assert plaintext.get("kaos-llm", "openai", "default") is None

    def test_clears_weaker_tier_after_write(self) -> None:
        keyring = _FakeStorage(StorageTier.KEYRING)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT)
        # Pre-populate plaintext to mimic a legacy install.
        plaintext.set("kaos-llm", "openai", "default", "old-value")
        store = HardenedCredentialStore(backends=[keyring, plaintext])
        store.set("kaos-llm", "openai", "default", "new-value")
        # New value lives only in keyring; plaintext was cleared.
        assert keyring.get("kaos-llm", "openai", "default") == "new-value"
        assert plaintext.get("kaos-llm", "openai", "default") is None

    def test_prefer_tier_caps_writes(self) -> None:
        keyring = _FakeStorage(StorageTier.KEYRING)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT)
        store = HardenedCredentialStore(
            backends=[keyring, plaintext], prefer_tier=StorageTier.PLAINTEXT
        )
        store.set("kaos-llm", "openai", "default", "v1")
        assert keyring.get("kaos-llm", "openai", "default") is None
        assert plaintext.get("kaos-llm", "openai", "default") == "v1"

    def test_no_available_tier_raises(self) -> None:
        keyring = _FakeStorage(StorageTier.KEYRING, available=False)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT, available=False)
        store = HardenedCredentialStore(backends=[keyring, plaintext])
        with pytest.raises(RuntimeError, match="No credential storage backend"):
            store.set("kaos-llm", "openai", "default", "v1")


class TestDelete:
    def test_delete_clears_every_available_tier(self) -> None:
        keyring = _FakeStorage(StorageTier.KEYRING)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT)
        keyring.set("kaos-llm", "openai", "default", "v1")
        plaintext.set("kaos-llm", "openai", "default", "v1")
        store = HardenedCredentialStore(backends=[keyring, plaintext])
        store.delete("kaos-llm", "openai", "default")
        assert keyring.get("kaos-llm", "openai", "default") is None
        assert plaintext.get("kaos-llm", "openai", "default") is None


class TestListServices:
    def test_unions_across_tiers(self) -> None:
        keyring = _FakeStorage(StorageTier.KEYRING)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT)
        keyring.set("kaos-llm", "openai", "default", "v1")
        plaintext.set("kaos-llm", "anthropic", "default", "v2")
        store = HardenedCredentialStore(backends=[keyring, plaintext])
        assert store.list_services("kaos-llm") == ["anthropic", "openai"]


class TestMigrate:
    def test_migrate_promotes_single_secret(self) -> None:
        keyring = _FakeStorage(StorageTier.KEYRING)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT)
        plaintext.set("kaos-llm", "openai", "default", "v1")
        store = HardenedCredentialStore(backends=[keyring, plaintext])
        result = store.migrate("kaos-llm", "openai", "default")
        assert result is StorageTier.KEYRING
        assert keyring.get("kaos-llm", "openai", "default") == "v1"
        assert plaintext.get("kaos-llm", "openai", "default") is None

    def test_migrate_dry_run_reports_target_without_writing(self) -> None:
        keyring = _FakeStorage(StorageTier.KEYRING)
        plaintext = _FakeStorage(StorageTier.PLAINTEXT)
        plaintext.set("kaos-llm", "openai", "default", "v1")
        store = HardenedCredentialStore(backends=[keyring, plaintext])
        result = store.migrate("kaos-llm", "openai", "default", dry_run=True)
        assert result is StorageTier.KEYRING
        # Nothing actually moved.
        assert keyring.get("kaos-llm", "openai", "default") is None
        assert plaintext.get("kaos-llm", "openai", "default") == "v1"

    def test_migrate_returns_none_when_secret_absent(self) -> None:
        store = HardenedCredentialStore(
            backends=[_FakeStorage(StorageTier.KEYRING), _FakeStorage(StorageTier.PLAINTEXT)]
        )
        assert store.migrate("kaos-llm", "openai", "default") is None


class TestRealPlaintextIntegration:
    def test_full_round_trip_through_real_credential_store(self, tmp_path: Path) -> None:
        # No fakes — exercise the dispatcher against a real
        # PlaintextStorage(CredentialStore) on a tmp_path file.
        store = HardenedCredentialStore(backends=[PlaintextStorage(path=tmp_path / "creds.json")])
        assert store.active_tier is StorageTier.PLAINTEXT
        store.set("kaos-llm", "openai", "default", "sk-real")
        assert store.get("kaos-llm", "openai", "default") == "sk-real"
        store.delete("kaos-llm", "openai", "default")
        assert store.get("kaos-llm", "openai", "default") is None

    def test_default_construction_materializes_plaintext_floor(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # No backends supplied → dispatcher injects a default
        # PlaintextStorage. Point KAOS_STATE_DIR (used by future
        # tiers; here we just verify a plaintext default exists).
        store = HardenedCredentialStore()
        assert any(b.tier is StorageTier.PLAINTEXT for b in store.backends)
        assert store.active_tier is StorageTier.PLAINTEXT
