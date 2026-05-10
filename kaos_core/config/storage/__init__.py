"""Optional hardened credential & session storage.

This subpackage provides a tier-aware credential dispatcher that
sits between :func:`kaos_core.config.secrets.resolve_secret` and the
on-disk credential store. The base install ships only Tier 5
(plaintext, see :class:`kaos_core.config.CredentialStore`); higher
tiers light up when the corresponding extras are installed:

- ``kaos-core[keyring]`` → Tier 3 (OS keyring)
- ``kaos-core[encrypted-store]`` → Tier 4 (Fernet + Argon2id)

See ``docs/F2-HARDENED-STORAGE-DESIGN.md`` for the full design.
"""

from __future__ import annotations

from kaos_core.config.storage.base import SecretStorage, StorageTier
from kaos_core.config.storage.dispatcher import HardenedCredentialStore
from kaos_core.config.storage.keyring_backend import KeyringStorage
from kaos_core.config.storage.plaintext import PlaintextStorage
from kaos_core.config.storage.xdg import (
    kaos_cache_dir,
    kaos_config_dir,
    kaos_state_dir,
)

__all__ = [
    "HardenedCredentialStore",
    "KeyringStorage",
    "PlaintextStorage",
    "SecretStorage",
    "StorageTier",
    "kaos_cache_dir",
    "kaos_config_dir",
    "kaos_state_dir",
]
