from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

from kaos_core.logging import get_logger

logger = get_logger(__name__)


def _harden_owner_only(path: Path) -> None:
    """Restrict *path* to owner-only access using the OS's native primitive.

    POSIX
        ``chmod(0o600)`` — owner read/write, no group/other access.
        Enforced by the kernel's permission check.

    Windows / NTFS
        NTFS ignores POSIX mode bits; ``os.chmod`` only flips the
        read-only bit. Real owner-only access requires a Discretionary
        Access Control List (DACL). When ``pywin32`` is installed
        (``kaos-core[windows-secure]``), this function builds a DACL
        that grants the current user full control and grants nothing
        to anyone else, then applies it to *path*. When ``pywin32`` is
        NOT installed, this function logs a warning and returns —
        callers get the same plaintext file but without the
        owner-only ACL. The CredentialStore docstring documents this
        as an explicit limitation; production deployments should use
        a managed secrets service rather than relying on the
        plaintext store.
    """
    if sys.platform == "win32":
        try:
            _harden_owner_only_windows(path)
        except ImportError:
            logger.warning(
                "pywin32 is not installed; %s is not restricted to the "
                "current user. Install kaos-core[windows-secure] to "
                "enable NTFS DACL hardening.",
                path,
            )
        except OSError:
            # ACL operations can fail on network filesystems (SMB
            # mounts where the server doesn't honor DACL writes) and
            # on filesystems without DACL support (FAT32 USB drives).
            # Don't crash the credential write — log and continue with
            # the plaintext file in place.
            logger.warning(
                "Failed to apply NTFS DACL hardening to %s; the file "
                "may be readable by other users.",
                path,
                exc_info=True,
            )
    else:
        path.chmod(0o600)


def _harden_owner_only_windows(path: Path) -> None:
    """Apply an NTFS DACL granting full control to the current user only.

    Imported lazily so the module stays importable on systems without
    ``pywin32``. Raises ``ImportError`` if ``pywin32`` is missing.
    """
    import ntsecuritycon  # ty: ignore[unresolved-import]
    import win32api  # ty: ignore[unresolved-import]
    import win32security  # ty: ignore[unresolved-import]

    # ``GetUserName`` lives on ``win32api``, not ``win32security``;
    # ``LookupAccountName`` then maps the username to its SID.
    user_sid, _, _ = win32security.LookupAccountName("", win32api.GetUserName())
    descriptor = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
    dacl = win32security.ACL()
    dacl.AddAccessAllowedAce(
        win32security.ACL_REVISION,
        ntsecuritycon.FILE_ALL_ACCESS,
        user_sid,
    )
    descriptor.SetSecurityDescriptorDacl(1, dacl, 0)
    win32security.SetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION, descriptor)


class CredentialStore:
    """Plaintext file-backed credential store — **development / test use only**.

    This implementation stores credentials as JSON on disk. Owner-only
    access is enforced via the platform's native primitive:

    - **POSIX (Linux/macOS):** file mode ``0o600`` via ``chmod`` —
      owner read/write, no group/other.
    - **NTFS (Windows):** Discretionary Access Control List (DACL)
      granting full control to the current user only, applied via
      ``win32security`` (requires ``kaos-core[windows-secure]``).
      When ``pywin32`` is missing on Windows, the file is written
      plaintext with default ACLs and a warning is logged — the
      CredentialStore still functions but does NOT restrict access.

    Writes are atomic: sibling temp file + ``fsync`` + ``os.replace``
    in the same directory.

    .. warning::

       Do not use this for production secrets. The values are stored in
       plaintext and are recoverable by anyone (or any process) that can
       read the file. For production deployments, use:

       - Environment variables resolved through
         :func:`kaos_core.config.secrets.resolve_secret`,
       - A managed secrets service (Vault, AWS/GCP/Azure secret managers,
         Doppler, 1Password Connect, etc.), or
       - The OS keyring via the ``keyring`` package (planned for v0.2).

    Atomicity: the underlying ``os.replace`` rename is atomic on POSIX
    filesystems when source and destination share the same directory,
    which is the case here. Concurrent readers therefore always observe
    either the prior file or the new one — never a partial write.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(".kaos-credentials.json")

    def _load(self) -> dict[str, dict[str, dict[str, str]]]:
        if not self.path.exists():
            return {}
        return cast(dict[str, dict[str, dict[str, str]]], json.loads(self.path.read_text()))

    def _save(self, data: dict[str, dict[str, dict[str, str]]]) -> None:
        target = self.path.resolve()
        directory = target.parent
        directory.mkdir(parents=True, exist_ok=True)
        # Atomic write: same-directory temp file + fsync + os.replace.
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=".tmp-",
            suffix=target.suffix or ".json",
            delete=False,
        ) as tmp:
            json.dump(data, tmp, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        try:
            _harden_owner_only(tmp_path)
            tmp_path.replace(target)
        except Exception:
            # Best-effort cleanup of the orphaned temp file; never suppress
            # the underlying error.
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)
            raise

    def get(self, module: str, service: str, key: str = "default") -> str | None:
        return self._load().get(module, {}).get(service, {}).get(key)

    def set(self, module: str, service: str, key: str, value: str) -> None:
        data = self._load()
        data.setdefault(module, {}).setdefault(service, {})[key] = value
        self._save(data)

    def delete(self, module: str, service: str, key: str = "default") -> None:
        data = self._load()
        services = data.get(module)
        if not services:
            return
        keys = services.get(service)
        if not keys or key not in keys:
            return
        del keys[key]
        # Clean up empty containers so ``list_services`` doesn't keep
        # reporting the service after every key is gone.
        if not keys:
            services.pop(service, None)
            if not services:
                data.pop(module, None)
        self._save(data)

    def list_services(self, module: str) -> list[str]:
        return sorted(self._load().get(module, {}).keys())
