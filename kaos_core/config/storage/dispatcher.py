"""Tier-aware credential dispatcher.

Sits between :func:`kaos_core.config.secrets.resolve_secret` and the
concrete storage backends. On every read it walks the configured
backends from strongest to weakest, returning the first hit and —
when the hit was at a weaker tier — opportunistically migrating the
secret upward so subsequent reads are faster and weaker storage
holds nothing the stronger storage doesn't already hold. On every
write it stores in the strongest available tier and deletes from
weaker tiers, preventing stale plaintext lingering after an upgrade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kaos_core.config.storage.base import SecretStorage, StorageTier
from kaos_core.config.storage.plaintext import PlaintextStorage
from kaos_core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = get_logger(__name__)


class HardenedCredentialStore:
    """Tier-aware credential store.

    Drop-in replacement for :class:`kaos_core.config.CredentialStore`
    at the :func:`resolve_secret` call site. The
    :class:`SecretStorage` Protocol matches both, so passing a
    :class:`HardenedCredentialStore` or a plain
    :class:`CredentialStore` to ``resolve_secret`` continues to work.

    Construction is cheap; backend probing happens lazily on first
    read or write. Pass ``backends=`` to supply concrete instances
    (the recommended path for the F2.1 base install, which has only
    a plaintext tier). Higher-tier backends register themselves via
    F2.2 (keyring) and F2.3 (encrypted-file) by being included in
    ``backends`` — there is no hidden discovery mechanism.

    Args:
        backends: Iterable of concrete :class:`SecretStorage`
            instances, one per tier. Order does not matter; the
            dispatcher sorts by ``backend.tier`` (strongest first).
            If two backends share a tier, the later one wins —
            useful for tests.
        prefer_tier: Optional cap on the strongest tier the
            dispatcher will *write* to. Reads still consult every
            backend. Useful for forcing the encrypted-file tier in
            CI even when keyring is technically available.
    """

    def __init__(
        self,
        backends: Iterable[SecretStorage] | None = None,
        *,
        prefer_tier: StorageTier | None = None,
    ) -> None:
        # Always keep a plaintext tier. If the caller didn't supply
        # one we materialize a default — same path/policy as today's
        # CredentialStore.
        materialized = list(backends) if backends is not None else []
        if not any(b.tier is StorageTier.PLAINTEXT for b in materialized):
            materialized.append(PlaintextStorage())
        # Sort strongest first so iteration matches the design's
        # "first hit wins" rule.
        self._backends: list[SecretStorage] = sorted(
            materialized, key=lambda b: b.tier, reverse=True
        )
        self._prefer_tier = prefer_tier

    @property
    def backends(self) -> list[SecretStorage]:
        """Backends in dispatcher order (strongest tier first)."""
        return list(self._backends)

    @property
    def active_tier(self) -> StorageTier:
        """The strongest tier that is currently available, or ``NONE``."""
        for backend in self._backends:
            if backend.is_available() and (
                self._prefer_tier is None or backend.tier <= self._prefer_tier
            ):
                return backend.tier
        return StorageTier.NONE

    def _writable_backends(self) -> list[SecretStorage]:
        """Backends that are available right now AND within the cap."""
        return [
            b
            for b in self._backends
            if b.is_available() and (self._prefer_tier is None or b.tier <= self._prefer_tier)
        ]

    def get(self, module: str, service: str, key: str = "default") -> str | None:
        """Read in tier order; auto-migrate hits from weaker tiers upward.

        Iterates strongest tier first. On the first hit, if any
        *stronger* tier is available and currently empty, copy the
        value upward and delete it from the weaker tier. Migration
        failures log a warning but do not fail the read.
        """
        hit_backend: SecretStorage | None = None
        hit_value: str | None = None
        # Walk strongest → weakest; remember the first hit.
        for backend in self._backends:
            if not backend.is_available():
                continue
            try:
                value = backend.get(module, service, key)
            except (OSError, RuntimeError):
                logger.warning(
                    "Storage tier %s raised on get(%s/%s/%s); skipping",
                    backend.tier.name,
                    module,
                    service,
                    key,
                    exc_info=True,
                )
                continue
            if value is not None:
                hit_backend, hit_value = backend, value
                break

        if hit_backend is None or hit_value is None:
            return None

        # Auto-migrate upward: any stronger tier that is currently
        # available and within the prefer_tier cap should hold the
        # secret too. The migration is best-effort.
        self._maybe_migrate_upward(module, service, key, hit_value, source=hit_backend)
        return hit_value

    def set(self, module: str, service: str, key: str, value: str) -> None:
        """Write to the strongest available tier; clear from weaker tiers.

        If no tier is available this raises :class:`RuntimeError` —
        loud failure is preferable to silently dropping the secret.
        """
        writable = self._writable_backends()
        if not writable:
            msg = (
                "No credential storage backend is available. "
                "Install kaos-core[hardened] or ensure the plaintext store "
                "is writable."
            )
            raise RuntimeError(msg)

        target = writable[0]  # strongest
        target.set(module, service, key, value)
        logger.debug(
            "Wrote credential %s/%s/%s to tier %s",
            module,
            service,
            key,
            target.tier.name,
        )
        # Delete from any weaker tier so the strongest tier is the
        # single source of truth.
        for backend in writable[1:]:
            try:
                if backend.get(module, service, key) is not None:
                    backend.delete(module, service, key)
                    logger.debug(
                        "Cleared credential %s/%s/%s from weaker tier %s after write to %s",
                        module,
                        service,
                        key,
                        backend.tier.name,
                        target.tier.name,
                    )
            except (OSError, RuntimeError):
                logger.warning(
                    "Failed to clear credential %s/%s/%s from tier %s",
                    module,
                    service,
                    key,
                    backend.tier.name,
                    exc_info=True,
                )

    def delete(self, module: str, service: str, key: str = "default") -> None:
        """Delete from every available tier."""
        for backend in self._writable_backends():
            try:
                backend.delete(module, service, key)
            except (OSError, RuntimeError):
                logger.warning(
                    "Failed to delete %s/%s/%s from tier %s",
                    module,
                    service,
                    key,
                    backend.tier.name,
                    exc_info=True,
                )

    def list_services(self, module: str) -> list[str]:
        """Return the union of services across every available tier."""
        seen: set[str] = set()
        for backend in self._backends:
            if not backend.is_available():
                continue
            try:
                seen.update(backend.list_services(module))
            except (OSError, RuntimeError):
                logger.warning(
                    "list_services failed on tier %s",
                    backend.tier.name,
                    exc_info=True,
                )
        return sorted(seen)

    def migrate(
        self, module: str, service: str, key: str = "default", *, dry_run: bool = False
    ) -> StorageTier | None:
        """Move a single secret to the strongest available tier.

        Returns the tier it landed in, or ``None`` if the secret
        wasn't found in any tier. ``dry_run=True`` reports what
        *would* happen without writing.
        """
        # Find the secret in the weakest tier that has it. (We could
        # find it anywhere, but starting from the weakest is the
        # case where migration matters.)
        for backend in reversed(self._backends):
            if not backend.is_available():
                continue
            value = backend.get(module, service, key)
            if value is None:
                continue
            target_candidates = [
                b
                for b in self._backends
                if b.tier > backend.tier
                and b.is_available()
                and (self._prefer_tier is None or b.tier <= self._prefer_tier)
            ]
            if not target_candidates:
                return backend.tier  # already at strongest
            target = target_candidates[0]
            if dry_run:
                return target.tier
            target.set(module, service, key, value)
            backend.delete(module, service, key)
            logger.info(
                "Migrated credential %s/%s/%s from tier %s to tier %s",
                module,
                service,
                key,
                backend.tier.name,
                target.tier.name,
            )
            return target.tier
        return None

    def _maybe_migrate_upward(
        self,
        module: str,
        service: str,
        key: str,
        value: str,
        *,
        source: SecretStorage,
    ) -> None:
        # Promote into stronger available tiers. Best-effort — never
        # raise out of a get().
        promoted = False
        for backend in self._backends:
            if backend is source:
                break  # already at-or-stronger-than source
            if not backend.is_available():
                continue
            if self._prefer_tier is not None and backend.tier > self._prefer_tier:
                continue
            try:
                if backend.get(module, service, key) is None:
                    backend.set(module, service, key, value)
                    promoted = True
                    logger.info(
                        "Auto-migrated credential %s/%s/%s upward from tier %s to tier %s",
                        module,
                        service,
                        key,
                        source.tier.name,
                        backend.tier.name,
                    )
            except (OSError, RuntimeError):
                logger.warning(
                    "Auto-migration of %s/%s/%s into tier %s failed",
                    module,
                    service,
                    key,
                    backend.tier.name,
                    exc_info=True,
                )
        if not promoted:
            return
        # Once promoted, remove from the source so the strongest tier
        # is authoritative.
        try:
            source.delete(module, service, key)
        except (OSError, RuntimeError):
            logger.warning(
                "Failed to clear migrated credential %s/%s/%s from source tier %s",
                module,
                service,
                key,
                source.tier.name,
                exc_info=True,
            )


__all__ = ["HardenedCredentialStore"]
