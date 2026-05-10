"""Tests for the storage Protocol + tier enum.

The Protocol is structural so no runtime check is enforced; these
tests pin the *integer ordering* of tiers (which the dispatcher
relies on for "strongest available wins") and the canonical values,
so a future addition or renumbering can't silently change behavior.
"""

from __future__ import annotations

from kaos_core.config.storage.base import StorageTier


class TestStorageTierOrdering:
    def test_stronger_tiers_compare_greater(self) -> None:
        assert StorageTier.NONE < StorageTier.PLAINTEXT
        assert StorageTier.PLAINTEXT < StorageTier.ENCRYPTED_FILE
        assert StorageTier.ENCRYPTED_FILE < StorageTier.KEYRING
        assert StorageTier.KEYRING < StorageTier.SYSTEM_BROKER

    def test_int_values_pin_sort_order(self) -> None:
        # Members are spaced by 10 so future tiers can slot in
        # without renumbering. The exact spacing isn't part of the
        # public contract, but the sort order is, so we pin both.
        assert StorageTier.NONE.value == 0
        assert StorageTier.PLAINTEXT.value == 10
        assert StorageTier.ENCRYPTED_FILE.value == 20
        assert StorageTier.KEYRING.value == 30
        assert StorageTier.SYSTEM_BROKER.value == 40

    def test_max_returns_strongest(self) -> None:
        # ``max(...)`` is what the dispatcher uses; verify
        # IntEnum semantics make it return the strongest by tier.
        tiers = [StorageTier.PLAINTEXT, StorageTier.KEYRING, StorageTier.ENCRYPTED_FILE]
        assert max(tiers) is StorageTier.KEYRING
