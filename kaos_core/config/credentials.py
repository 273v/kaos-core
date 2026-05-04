from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast


class CredentialStore:
    """Plaintext file-backed credential store — **development / test use only**.

    This implementation stores credentials as JSON on disk with file mode
    ``0o600`` (owner read/write only) and writes atomically (sibling temp
    file + ``fsync`` + rename). It is suitable for local development and
    CI, where machine-level isolation is acceptable.

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
            tmp_path.chmod(0o600)
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
        service_data = data.get(module, {}).get(service, {})
        service_data.pop(key, None)
        self._save(data)

    def list_services(self, module: str) -> list[str]:
        return sorted(self._load().get(module, {}).keys())
