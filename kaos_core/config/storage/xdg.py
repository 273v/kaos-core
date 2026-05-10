"""XDG / Known-Folder path resolver for kaos-core.

Tokens and credentials are *runtime state*, not user *config*. They
live under ``$XDG_STATE_HOME`` (default ``~/.local/state``), not
``$XDG_CONFIG_HOME`` (default ``~/.config``) — users routinely sync
``~/.config`` into dotfile repos, rarely ``~/.local/state``. On
Windows we use ``%LOCALAPPDATA%`` and never ``%APPDATA%``: DPAPI
master keys are bound to the local user's logon and don't decrypt
cleanly when a roaming profile carries the file to another machine.

Three top-level helpers are exported, each honoring an explicit
``KAOS_*_DIR`` override (useful for tests, containers, and
side-by-side profile layouts):

- :func:`kaos_config_dir` — non-secret configuration files
- :func:`kaos_state_dir` — credentials, refresh tokens, session state
- :func:`kaos_cache_dir` — ephemeral / regenerable artifacts

The helpers do not create the directory; callers ``mkdir(parents=True,
exist_ok=True)`` when they actually need to write.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_KAOS = "kaos"


def _from_env(name: str) -> Path | None:
    """Return ``Path(os.environ[name])`` if set non-empty, else ``None``."""
    value = os.environ.get(name)
    if value and value.strip():
        return Path(value)
    return None


def _windows_local_appdata() -> Path:
    """Return ``%LOCALAPPDATA%``, falling back to ``~/AppData/Local``.

    Avoids ``%APPDATA%`` (the *roaming* profile dir) on purpose —
    DPAPI-encrypted blobs that ride a roaming profile to a different
    machine cannot be decrypted there, so we keep all kaos state
    machine-local.
    """
    if (override := _from_env("LOCALAPPDATA")) is not None:
        return override
    return Path.home() / "AppData" / "Local"


def kaos_config_dir() -> Path:
    """Return the kaos non-secret configuration directory.

    Resolution order:

    1. ``KAOS_CONFIG_DIR`` environment variable (override).
    2. Windows: ``%LOCALAPPDATA%/kaos/config``.
    3. POSIX/macOS: ``$XDG_CONFIG_HOME/kaos`` if set, else
       ``~/.config/kaos``.
    """
    if (override := _from_env("KAOS_CONFIG_DIR")) is not None:
        return override
    if sys.platform == "win32":
        return _windows_local_appdata() / _KAOS / "config"
    base = _from_env("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return base / _KAOS


def kaos_state_dir() -> Path:
    """Return the kaos state directory (credentials, refresh tokens).

    Resolution order:

    1. ``KAOS_STATE_DIR`` environment variable (override).
    2. Windows: ``%LOCALAPPDATA%/kaos/state``.
    3. POSIX/macOS: ``$XDG_STATE_HOME/kaos`` if set, else
       ``~/.local/state/kaos``.

    Per-user, per-machine. Should not be synced to dotfile repos or
    cloud backups (see module docstring for why).
    """
    if (override := _from_env("KAOS_STATE_DIR")) is not None:
        return override
    if sys.platform == "win32":
        return _windows_local_appdata() / _KAOS / "state"
    base = _from_env("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return base / _KAOS


def kaos_cache_dir() -> Path:
    """Return the kaos cache directory (ephemeral / regenerable).

    Resolution order:

    1. ``KAOS_CACHE_DIR`` environment variable (override).
    2. Windows: ``%LOCALAPPDATA%/kaos/cache``.
    3. POSIX/macOS: ``$XDG_CACHE_HOME/kaos`` if set, else
       ``~/.cache/kaos``.
    """
    if (override := _from_env("KAOS_CACHE_DIR")) is not None:
        return override
    if sys.platform == "win32":
        return _windows_local_appdata() / _KAOS / "cache"
    base = _from_env("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return base / _KAOS


__all__ = ["kaos_cache_dir", "kaos_config_dir", "kaos_state_dir"]
