"""Tier 5 adapter: wrap :class:`CredentialStore` as a :class:`SecretStorage`.

The existing :class:`kaos_core.config.CredentialStore` already speaks
the ``(module, service, key)`` keyspace and ships the F1 hardening
(``chmod 0o600`` on POSIX, NTFS DACL on Windows when the
``windows-secure`` extra is installed). This adapter adds the
:class:`SecretStorage` Protocol fields (``tier``, ``is_available``)
without touching the underlying class — keeping ``CredentialStore``
usable on its own and letting the dispatcher treat it as a tier-5
backend through the same interface as keyring / encrypted-file.
"""

from __future__ import annotations

from pathlib import Path

from kaos_core.config.credentials import CredentialStore
from kaos_core.config.storage.base import StorageTier


class PlaintextStorage:
    """Tier-5 adapter over :class:`CredentialStore`.

    Holds a single :class:`CredentialStore` and forwards every
    Protocol method to it. The plaintext tier is *always* available
    in the sense that we can always create the JSON file; the
    dispatcher still consults :meth:`is_available` so test doubles
    can disable it.
    """

    tier = StorageTier.PLAINTEXT

    def __init__(self, store: CredentialStore | None = None, *, path: Path | None = None) -> None:
        if store is not None and path is not None:
            msg = "Pass either store= or path=, not both"
            raise ValueError(msg)
        self._store = store if store is not None else CredentialStore(path)

    @property
    def store(self) -> CredentialStore:
        """The underlying :class:`CredentialStore`. Useful for migration code."""
        return self._store

    def get(self, module: str, service: str, key: str = "default") -> str | None:
        return self._store.get(module, service, key)

    def set(self, module: str, service: str, key: str, value: str) -> None:
        self._store.set(module, service, key, value)

    def delete(self, module: str, service: str, key: str = "default") -> None:
        self._store.delete(module, service, key)

    def list_services(self, module: str) -> list[str]:
        return self._store.list_services(module)

    def is_available(self) -> bool:
        # The plaintext tier is the floor — always available. Even
        # when the parent directory doesn't exist yet,
        # ``CredentialStore._save`` mkdirs it on first write.
        return True


__all__ = ["PlaintextStorage"]
