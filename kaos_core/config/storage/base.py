"""Protocol + tier enum for the hardened credential dispatcher.

Defines the abstraction every concrete backend implements
(:class:`SecretStorage`) and the comparable ordering of backends
(:class:`StorageTier`). Backends and the dispatcher live in sibling
modules; this one is import-cheap and dependency-free.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Protocol, runtime_checkable


class StorageTier(IntEnum):
    """Comparable ordering of credential-storage strength.

    Stronger tiers get a higher integer. The dispatcher reads from
    every available tier and returns the first hit; it writes to the
    strongest available tier and deletes from any weaker tier where
    the same secret was found, so an upgrade path doesn't leave
    plaintext lingering.

    Members are spaced by 10 so future tiers slot in without
    renumbering.

    - ``NONE`` (0) — sentinel for "not found / unavailable".
    - ``PLAINTEXT`` (10) — JSON file with mode ``0o600`` on POSIX or
      NTFS DACL on Windows. The current
      :class:`kaos_core.config.CredentialStore` ships this tier.
    - ``ENCRYPTED_FILE`` (20) — Fernet ciphertext with an Argon2id-
      derived KEK. Requires the ``encrypted-store`` extra; landed in
      F2.3.
    - ``KEYRING`` (30) — OS-native credential vault via the
      ``keyring`` package (macOS Keychain, Windows Credential
      Manager, libsecret/Secret Service, KWallet). Requires the
      ``keyring`` extra; landed in F2.2.
    - ``SYSTEM_BROKER`` (40) — reserved for future broker
      integrations (Microsoft WAM, macOS PRT) that go beyond what
      ``keyring`` exposes.
    """

    NONE = 0
    PLAINTEXT = 10
    ENCRYPTED_FILE = 20
    KEYRING = 30
    SYSTEM_BROKER = 40


@runtime_checkable
class SecretStorage(Protocol):
    """A keyed credential store with availability probing.

    Implementations are keyed by ``(module, service, key)``. ``module``
    is a kaos-* package name (e.g. ``"kaos-llm"``); ``service`` is the
    upstream provider (e.g. ``"openai"``); ``key`` distinguishes
    multiple credentials for the same provider (e.g. ``"default"``,
    ``"production"``).

    Concrete implementations declare their tier via the class
    attribute ``tier`` and report runtime availability via
    :meth:`is_available`. The dispatcher uses both to pick which
    backend handles each call.
    """

    tier: StorageTier

    def get(self, module: str, service: str, key: str = "default") -> str | None:
        """Return the stored secret value or ``None`` if absent."""
        ...

    def set(self, module: str, service: str, key: str, value: str) -> None:
        """Store *value* under ``(module, service, key)``, overwriting any existing entry."""
        ...

    def delete(self, module: str, service: str, key: str = "default") -> None:
        """Remove the entry at ``(module, service, key)``. No-op when absent."""
        ...

    def list_services(self, module: str) -> list[str]:
        """Return the sorted list of services known under *module*."""
        ...

    def is_available(self) -> bool:
        """Return ``True`` if this backend can read and write today.

        ``False`` covers missing optional dependencies, missing
        backend daemons (no D-Bus session for libsecret), missing
        passphrases, and any other condition that would make a
        ``get``/``set`` call fail. Backends should be conservative —
        return ``False`` rather than raise from this method.
        """
        ...


__all__ = ["SecretStorage", "StorageTier"]
