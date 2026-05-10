"""Tier 3 — OS keyring backend.

Wraps the third-party ``keyring`` package (macOS Keychain, Windows
Credential Manager / WinVault, Linux libsecret / Secret Service,
KDE Wallet) behind the :class:`SecretStorage` Protocol. Lazily
imports ``keyring`` so the base ``kaos_core.config.storage`` package
remains importable without the optional dependency.

Probe rules (the dispatcher reports this tier "available" only when
ALL hold):

- ``keyring`` is importable (``kaos-core[keyring]`` extra installed).
- ``keyring.get_keyring()`` returns a backend with ``priority >= 1``
  — rejects the inert ``Fail`` keyring.
- The backend module is **not** ``keyrings.alt.*`` — those backends
  silently store plaintext under ``~/.local/share/python_keyring/``,
  which would make "keyring success" a lie.
- We are not on a headless Linux session (no ``DISPLAY``,
  ``WAYLAND_DISPLAY``, AND no TTY) unless ``KAOS_FORCE_KEYRING=1``.
- We are not in WSL unless ``KAOS_WSL_USE_KEYRING=1``. The libsecret
  D-Bus session under WSL is unreliable; default-off.

The keyring API has no cross-backend enumeration primitive, so
:meth:`list_services` is backed by a small JSON *index* in
``$XDG_STATE_HOME/kaos/credentials.keyring.index.json`` recording
the ``(module, service, key)`` tuples we have written. The index
holds **no secret values** — only names. Loss or tampering with the
index makes ``list_services`` incomplete until the next write; it
does not expose any secret.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from kaos_core.config.storage.base import StorageTier
from kaos_core.config.storage.xdg import kaos_state_dir
from kaos_core.logging import get_logger

logger = get_logger(__name__)

_REJECTED_BACKEND_PREFIX = "keyrings.alt."


def _is_headless_linux() -> bool:
    """Return True when running on Linux without a usable session.

    The libsecret D-Bus probe is slow (multi-second) and hangs on
    locked collections; default-off whenever there's no realistic
    way for the user to authorize a prompt. Override with
    ``KAOS_FORCE_KEYRING=1``.
    """
    if sys.platform != "linux":
        return False
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return False
    try:
        return not sys.stdout.isatty()
    except (AttributeError, ValueError):  # detached stdout
        return True


def _is_wsl() -> bool:
    """Return True when the kernel reports it's WSL."""
    if sys.platform != "linux":
        return False
    try:
        with Path("/proc/version").open(encoding="utf-8") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


class KeyringStorage:
    """Tier-3 backend using the ``keyring`` package.

    Args:
        profile: Profile name to scope the keyring service identifier.
            Lets multiple kaos-core profiles coexist without
            colliding on Keychain / Credential Manager service
            names.
        index_path: Override path for the (module, service, key)
            index file. Default is
            ``kaos_state_dir() / 'credentials.keyring.index.json'``.
        keyring_module: Inject a pre-imported ``keyring``-shaped
            module (testing). Default is ``None`` → lazy-import.
        force_available: Force the probe result for testing. Default
            ``None`` → probe normally.
    """

    tier = StorageTier.KEYRING

    def __init__(
        self,
        *,
        profile: str = "default",
        index_path: Path | None = None,
        keyring_module: Any = None,
        force_available: bool | None = None,
    ) -> None:
        self._profile = profile
        self._index_path = index_path or (kaos_state_dir() / "credentials.keyring.index.json")
        self._injected = keyring_module
        self._force_available = force_available

    # ──────────────── Protocol API ────────────────

    def is_available(self) -> bool:
        if self._force_available is not None:
            return self._force_available
        return self._probe()

    def get(self, module: str, service: str, key: str = "default") -> str | None:
        if not self.is_available():
            return None
        keyring = self._import_keyring()
        if keyring is None:
            return None
        try:
            return keyring.get_password(self._service_name(module, service), self._username(key))
        except Exception:
            logger.warning(
                "keyring.get_password failed for %s/%s/%s", module, service, key, exc_info=True
            )
            return None

    def set(self, module: str, service: str, key: str, value: str) -> None:
        if not self.is_available():
            msg = "Keyring backend is not available"
            raise RuntimeError(msg)
        keyring = self._import_keyring()
        if keyring is None:
            msg = "Keyring backend is not available"
            raise RuntimeError(msg)
        keyring.set_password(self._service_name(module, service), self._username(key), value)
        self._index_add(module, service, key)

    def delete(self, module: str, service: str, key: str = "default") -> None:
        if not self.is_available():
            return
        keyring = self._import_keyring()
        if keyring is None:
            return
        try:
            keyring.delete_password(self._service_name(module, service), self._username(key))
        except Exception:
            # Includes PasswordDeleteError ("not found") and any
            # backend-specific permission error. Always remove from
            # the index even if the keyring delete fails so we don't
            # advertise a credential that may already be gone.
            logger.debug(
                "keyring.delete_password raised for %s/%s/%s",
                module,
                service,
                key,
                exc_info=True,
            )
        self._index_remove(module, service, key)

    def list_services(self, module: str) -> list[str]:
        return sorted(self._index_load().get(module, {}).keys())

    # ──────────────── identifiers ────────────────

    def _service_name(self, module: str, service: str) -> str:
        # ``::`` separator chosen so the service name parses back
        # cleanly via ``str.split("::")`` if needed for migration.
        return f"kaos-core::{self._profile}::{module}::{service}"

    def _username(self, key: str) -> str:
        return key

    # ──────────────── probe ────────────────

    def _probe(self) -> bool:
        if os.environ.get("KAOS_DISABLE_KEYRING") == "1":
            # Hard opt-out for CI / sandboxes / users who explicitly
            # don't want the OS keyring touched. Honored before any
            # platform-specific heuristic so it works on macOS /
            # Windows where Keychain / WinVault are otherwise always
            # considered available.
            logger.debug("keyring tier disabled: KAOS_DISABLE_KEYRING=1 set")
            return False
        if _is_headless_linux() and os.environ.get("KAOS_FORCE_KEYRING") != "1":
            logger.debug(
                "keyring tier disabled: headless Linux (set KAOS_FORCE_KEYRING=1 to override)"
            )
            return False
        if _is_wsl() and os.environ.get("KAOS_WSL_USE_KEYRING") != "1":
            logger.debug("keyring tier disabled: WSL (set KAOS_WSL_USE_KEYRING=1 to override)")
            return False
        keyring = self._import_keyring()
        if keyring is None:
            return False
        try:
            backend = keyring.get_keyring()
        except Exception:
            logger.debug("keyring.get_keyring raised", exc_info=True)
            return False
        priority = getattr(backend, "priority", 0) or 0
        if priority < 1:
            logger.debug(
                "keyring tier disabled: backend priority %s < 1 (%s)",
                priority,
                type(backend).__name__,
            )
            return False
        backend_module = type(backend).__module__
        if backend_module.startswith(_REJECTED_BACKEND_PREFIX):
            logger.warning(
                "keyring tier disabled: %s.%s would store secrets in plaintext "
                "under ~/.local/share/python_keyring/. Refusing to use this backend.",
                backend_module,
                type(backend).__name__,
            )
            return False
        return True

    def _import_keyring(self) -> Any | None:
        if self._injected is not None:
            return self._injected
        try:
            import keyring
        except ImportError:
            logger.debug("keyring not installed; tier-3 unavailable")
            return None
        return keyring

    # ──────────────── index ────────────────

    def _index_load(self) -> dict[str, dict[str, list[str]]]:
        if not self._index_path.exists():
            return {}
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("keyring index at %s is unreadable; treating as empty", self._index_path)
            return {}
        # Defensive shape check — the file may have been hand-edited.
        if not isinstance(data, dict):
            return {}
        return data

    def _index_save(self, index: dict[str, dict[str, list[str]]]) -> None:
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")

    def _index_add(self, module: str, service: str, key: str) -> None:
        index = self._index_load()
        services = index.setdefault(module, {})
        keys = services.setdefault(service, [])
        if key not in keys:
            keys.append(key)
            keys.sort()
            self._index_save(index)

    def _index_remove(self, module: str, service: str, key: str) -> None:
        index = self._index_load()
        services = index.get(module)
        if not services:
            return
        keys = services.get(service)
        if not keys or key not in keys:
            return
        keys.remove(key)
        if not keys:
            services.pop(service, None)
            if not services:
                index.pop(module, None)
        self._index_save(index)


__all__ = ["KeyringStorage"]
