"""Tier 4 — encrypted-file backend (Fernet + Argon2id KEK).

Stores credentials in a single ``credentials.enc`` envelope file
under ``$XDG_STATE_HOME/kaos/`` (or wherever
:func:`kaos_state_dir` resolves). Each operation re-decrypts the
file in memory; the derived key is cached on the instance so
repeated reads in one session don't pay the Argon2id cost twice.

Threat model (vs. Tier-5 plaintext):

- Local-user file-mode boundary — equivalent (both write 0o600).
- Backup / Dropbox / Time Machine sync leak — **strictly better**:
  the file is ciphertext under a passphrase the sync backup never
  sees.
- Stolen unencrypted disk — equivalent to plaintext-with-passphrase
  in keyring; better than plaintext-only-on-disk.
- Same-user malware — partial. The decrypt path runs in-process; an
  attacker that owns the same user can attach to the running
  process and grab the cached key.

Passphrase source priority (the dispatcher's
:meth:`is_available` check returns False if no passphrase can be
obtained):

    1. ``KAOS_PASSPHRASE`` environment variable.
    2. Keyring entry ``kaos-core::{profile}::__kek__`` /
       ``__passphrase__`` (if the keyring tier is itself available).
    3. Caller-supplied :class:`PassphraseProvider`.

A passphrase provider that prompts interactively belongs to the
F2.5 CLI surface — this module stays library-pure.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

from kaos_core.config.credentials import _harden_owner_only
from kaos_core.config.storage.base import StorageTier
from kaos_core.config.storage.envelope import (
    Envelope,
    KdfParams,
    _get_invalid_token_class,
    decrypt,
    encrypt,
)
from kaos_core.config.storage.xdg import kaos_state_dir
from kaos_core.logging import get_logger

logger = get_logger(__name__)

PassphraseProvider = Callable[[], str | None]
"""Callable that returns the encrypted-store passphrase or ``None``."""


def env_passphrase_provider() -> str | None:
    """Default passphrase provider — reads ``KAOS_PASSPHRASE`` from the environment."""
    value = os.environ.get("KAOS_PASSPHRASE")
    if value and value.strip():
        return value
    return None


class EncryptedFileStorage:
    """Tier-4 backend storing credentials in a Fernet-encrypted envelope.

    Args:
        profile: Profile name. Reserved for future per-profile file
            naming; the v1 layout puts a single file at
            ``kaos_state_dir() / "credentials.enc"`` regardless.
        path: Override the credentials file path. Default is
            ``kaos_state_dir() / "credentials.enc"``.
        passphrase_provider: Callable returning the passphrase. Use
            :func:`env_passphrase_provider` for the standard env-var
            chain, or chain custom providers (CLI prompt, keyring
            stash, etc.) via :class:`ChainedProvider`.
        kdf_params: Override Argon2id parameters for new files.
            Existing files use whatever parameters their envelope
            recorded. Tests pass small values for speed.
    """

    tier = StorageTier.ENCRYPTED_FILE

    def __init__(
        self,
        *,
        profile: str = "default",
        path: Path | None = None,
        passphrase_provider: PassphraseProvider | None = None,
        kdf_params: KdfParams | None = None,
    ) -> None:
        self._profile = profile
        self._path = path or (kaos_state_dir() / "credentials.enc")
        self._provider = passphrase_provider or env_passphrase_provider
        self._kdf_params_override = kdf_params
        # Cache the decrypted dict + the matching passphrase in
        # memory so repeated reads don't pay Argon2id every time.
        self._cache_passphrase: str | None = None
        self._cache_data: dict[str, dict[str, dict[str, str]]] | None = None

    # ──────────────── Protocol API ────────────────

    def is_available(self) -> bool:
        # Probe: cryptography importable AND a passphrase resolvable.
        # Importing the InvalidToken class proves the
        # ``encrypted-store`` extra is installed; if not, this tier
        # silently disables itself rather than raising at probe time.
        try:
            _get_invalid_token_class()
        except ImportError:
            return False
        try:
            passphrase = self._provider()
        except Exception:
            logger.debug("encrypted-file passphrase provider raised", exc_info=True)
            return False
        return passphrase is not None

    def get(self, module: str, service: str, key: str = "default") -> str | None:
        data = self._load_data()
        if data is None:
            return None
        return data.get(module, {}).get(service, {}).get(key)

    def set(self, module: str, service: str, key: str, value: str) -> None:
        data = self._load_data() or {}
        data.setdefault(module, {}).setdefault(service, {})[key] = value
        self._save_data(data)

    def delete(self, module: str, service: str, key: str = "default") -> None:
        data = self._load_data()
        if data is None:
            return
        services = data.get(module)
        if not services:
            return
        keys = services.get(service)
        if not keys or key not in keys:
            return
        del keys[key]
        if not keys:
            services.pop(service, None)
            if not services:
                data.pop(module, None)
        self._save_data(data)

    def list_services(self, module: str) -> list[str]:
        data = self._load_data()
        if data is None:
            return []
        return sorted(data.get(module, {}).keys())

    # ──────────────── helpers ────────────────

    def _passphrase(self) -> str:
        passphrase = self._provider()
        if passphrase is None:
            msg = (
                "Encrypted credential store passphrase is not available. "
                "Set KAOS_PASSPHRASE or supply a passphrase_provider."
            )
            raise RuntimeError(msg)
        return passphrase

    def _load_data(self) -> dict[str, dict[str, dict[str, str]]] | None:
        if not self._path.exists():
            return None

        passphrase = self._passphrase()
        if (
            self._cache_data is not None
            and self._cache_passphrase is not None
            and self._cache_passphrase == passphrase
        ):
            return self._cache_data

        try:
            envelope_bytes = self._path.read_bytes()
        except OSError:
            logger.warning("Failed to read encrypted store at %s", self._path, exc_info=True)
            return None
        try:
            envelope = Envelope.deserialize(envelope_bytes)
        except (ValueError, json.JSONDecodeError) as exc:
            msg = f"Encrypted store at {self._path} is malformed: {exc}"
            raise RuntimeError(msg) from exc
        try:
            plaintext = decrypt(envelope, passphrase)
        except _get_invalid_token_class() as exc:
            msg = (
                f"Failed to decrypt {self._path}. The passphrase may be wrong, "
                "or the file may have been tampered with."
            )
            raise RuntimeError(msg) from exc
        data = json.loads(plaintext.decode("utf-8"))
        self._cache_passphrase = passphrase
        self._cache_data = data
        return data

    def _save_data(self, data: dict[str, dict[str, dict[str, str]]]) -> None:
        passphrase = self._passphrase()
        plaintext = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
        # Reuse the existing envelope's KDF params when possible so
        # we don't roll the salt + KDF on every write — that would
        # be both wasteful and confuse forensic analysis. New files
        # use the override (if any) or defaults.
        existing_kdf: KdfParams | None = None
        if self._path.exists():
            try:
                existing_envelope = Envelope.deserialize(self._path.read_bytes())
                existing_kdf = existing_envelope.kdf
            except (ValueError, json.JSONDecodeError, OSError):
                existing_kdf = None
        kdf = existing_kdf or self._kdf_params_override
        envelope = encrypt(plaintext, passphrase, kdf=kdf)
        self._atomic_write(envelope.serialize())
        self._cache_passphrase = passphrase
        self._cache_data = data

    def _atomic_write(self, payload: bytes) -> None:
        target = self._path.resolve()
        directory = target.parent
        directory.mkdir(parents=True, exist_ok=True)
        # Same atomic-replace pattern as CredentialStore: sibling
        # temp file + fsync + os.replace, with owner-only hardening
        # applied before the replace so the new file is hardened
        # from the moment it appears.
        with NamedTemporaryFile(
            mode="wb",
            dir=directory,
            prefix=".tmp-",
            suffix=target.suffix or ".enc",
            delete=False,
        ) as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        try:
            self._harden(tmp_path)
            tmp_path.replace(target)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _harden(path: Path) -> None:
        """Owner-only file mode (POSIX) / NTFS DACL (Windows).

        Delegates to the platform-aware helper shared with
        :class:`CredentialStore` so the encrypted file gets the same
        F1.5 hardening as the plaintext file.
        """
        _harden_owner_only(path)


__all__ = ["EncryptedFileStorage", "PassphraseProvider", "env_passphrase_provider"]
