"""Versioned ciphertext envelope for the encrypted-file tier.

The envelope is the on-disk format that wraps a Fernet ciphertext
with the KDF parameters needed to re-derive the key. Splitting it
out from the storage backend keeps the format documented and
testable in isolation, and lets us version/rotate the KDF or cipher
in a backwards-compatible way.

On-disk JSON shape (``version: 1``)::

    {
      "version": 1,
      "kdf": {
        "algorithm": "argon2id",
        "salt": "<base64url 16 bytes>",
        "memory_cost_kib": 65536,
        "iterations": 3,
        "lanes": 4
      },
      "cipher": "fernet",
      "ciphertext": "<urlsafe-b64 Fernet token>",
      "created_at": "2026-05-10T17:30:00Z",
      "rotated_at": null
    }

KDF parameters follow OWASP 2026 desktop-interactive guidance: 64
MiB memory, 3 iterations, 4 lanes. Tests override to small values
(e.g. 8 KiB / 1 iteration) to keep the suite fast — the envelope
records what was actually used so the file can always be decrypted.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryptography.fernet import InvalidToken as InvalidToken  # re-export for typing

ENVELOPE_VERSION = 1
DEFAULT_SALT_BYTES = 16
# OWASP 2026 desktop-interactive Argon2id parameters.
DEFAULT_MEMORY_COST_KIB = 65_536  # 64 MiB
DEFAULT_ITERATIONS = 3
DEFAULT_LANES = 4


@dataclass(frozen=True)
class KdfParams:
    """Argon2id parameters serialized into the envelope.

    Stored as plaintext JSON inside the envelope so the file can be
    decrypted on any host that has the passphrase, even if our
    defaults change. ``memory_cost_kib`` is in KiB (matching the
    Argon2 reference implementation's units).
    """

    algorithm: str = "argon2id"
    salt: bytes = b""
    memory_cost_kib: int = DEFAULT_MEMORY_COST_KIB
    iterations: int = DEFAULT_ITERATIONS
    lanes: int = DEFAULT_LANES

    @classmethod
    def fresh(
        cls,
        *,
        memory_cost_kib: int = DEFAULT_MEMORY_COST_KIB,
        iterations: int = DEFAULT_ITERATIONS,
        lanes: int = DEFAULT_LANES,
    ) -> KdfParams:
        return cls(
            salt=secrets.token_bytes(DEFAULT_SALT_BYTES),
            memory_cost_kib=memory_cost_kib,
            iterations=iterations,
            lanes=lanes,
        )

    def to_json(self) -> dict[str, str | int]:
        return {
            "algorithm": self.algorithm,
            "salt": base64.urlsafe_b64encode(self.salt).decode("ascii"),
            "memory_cost_kib": self.memory_cost_kib,
            "iterations": self.iterations,
            "lanes": self.lanes,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> KdfParams:
        if data.get("algorithm") != "argon2id":
            msg = f"Unsupported KDF algorithm: {data.get('algorithm')!r}"
            raise ValueError(msg)
        salt_b64 = data.get("salt")
        if not isinstance(salt_b64, str):
            msg = "Envelope salt is missing or malformed"
            raise ValueError(msg)
        memory_cost = data.get("memory_cost_kib", DEFAULT_MEMORY_COST_KIB)
        iterations = data.get("iterations", DEFAULT_ITERATIONS)
        lanes = data.get("lanes", DEFAULT_LANES)
        if (
            not isinstance(memory_cost, int)
            or not isinstance(iterations, int)
            or not isinstance(lanes, int)
        ):
            msg = "Envelope KDF integer parameters are malformed"
            raise ValueError(msg)
        return cls(
            salt=base64.urlsafe_b64decode(salt_b64.encode("ascii")),
            memory_cost_kib=memory_cost,
            iterations=iterations,
            lanes=lanes,
        )


@dataclass(frozen=True)
class Envelope:
    """Decoded representation of the on-disk envelope JSON."""

    version: int
    kdf: KdfParams
    cipher: str  # always "fernet" in v1
    ciphertext: bytes  # urlsafe-b64 Fernet token (kept as bytes for Fernet API)
    created_at: str
    rotated_at: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "version": self.version,
            "kdf": self.kdf.to_json(),
            "cipher": self.cipher,
            "ciphertext": self.ciphertext.decode("ascii"),
            "created_at": self.created_at,
            "rotated_at": self.rotated_at,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Envelope:
        version_raw = data.get("version", 0)
        if not isinstance(version_raw, int):
            msg = "Envelope version is missing or malformed"
            raise ValueError(msg)
        if version_raw != ENVELOPE_VERSION:
            msg = f"Unsupported envelope version: {version_raw}"
            raise ValueError(msg)
        kdf_raw = data.get("kdf")
        if not isinstance(kdf_raw, dict):
            msg = "Envelope KDF block is missing or malformed"
            raise ValueError(msg)
        cipher = data.get("cipher")
        if not isinstance(cipher, str) or cipher != "fernet":
            msg = f"Unsupported cipher: {cipher!r}"
            raise ValueError(msg)
        ciphertext = data.get("ciphertext")
        if not isinstance(ciphertext, str):
            msg = "Envelope ciphertext is missing or malformed"
            raise ValueError(msg)
        created_at = data.get("created_at")
        if not isinstance(created_at, str):
            msg = "Envelope created_at is missing or malformed"
            raise ValueError(msg)
        rotated_at = data.get("rotated_at")
        if rotated_at is not None and not isinstance(rotated_at, str):
            msg = "Envelope rotated_at is malformed"
            raise ValueError(msg)
        return cls(
            version=version_raw,
            kdf=KdfParams.from_json(kdf_raw),
            cipher=cipher,
            ciphertext=ciphertext.encode("ascii"),
            created_at=created_at,
            rotated_at=rotated_at,
        )

    def serialize(self) -> bytes:
        """Return the on-disk JSON bytes (UTF-8, sorted keys)."""
        return json.dumps(self.to_json(), indent=2, sort_keys=True).encode("utf-8")

    @classmethod
    def deserialize(cls, data: bytes) -> Envelope:
        return cls.from_json(json.loads(data.decode("utf-8")))


def _derive_fernet_key(passphrase: str, kdf: KdfParams) -> bytes:
    """Derive a urlsafe-base64-encoded 32-byte Fernet key from passphrase + KDF params.

    Imports ``cryptography`` lazily so this module loads cleanly in
    base installs that didn't pull the ``encrypted-store`` extra. The
    only paths that actually need ``cryptography`` are
    encrypt/decrypt/rotate; importing the module to read the
    :class:`Envelope` dataclass alone is fine.
    """
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

    raw = Argon2id(
        salt=kdf.salt,
        length=32,
        iterations=kdf.iterations,
        lanes=kdf.lanes,
        memory_cost=kdf.memory_cost_kib,
    ).derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def encrypt(
    plaintext: bytes,
    passphrase: str,
    *,
    kdf: KdfParams | None = None,
) -> Envelope:
    """Encrypt *plaintext* under a passphrase, returning a fresh envelope.

    A new random salt is generated on every call (unless *kdf* is
    supplied with an existing salt — used by ``encrypt_with_existing``
    to rewrap without changing the salt). Fernet timestamps the
    ciphertext, so two consecutive calls produce different tokens
    even with identical inputs.
    """
    from cryptography.fernet import Fernet

    params = kdf if kdf is not None else KdfParams.fresh()
    if not params.salt:
        params = replace(params, salt=secrets.token_bytes(DEFAULT_SALT_BYTES))
    key = _derive_fernet_key(passphrase, params)
    ciphertext = Fernet(key).encrypt(plaintext)
    return Envelope(
        version=ENVELOPE_VERSION,
        kdf=params,
        cipher="fernet",
        ciphertext=ciphertext,
        created_at=datetime.now(tz=UTC).isoformat(),
    )


def decrypt(envelope: Envelope, passphrase: str) -> bytes:
    """Decrypt an envelope. Raises :class:`InvalidToken` on bad passphrase or tamper."""
    from cryptography.fernet import Fernet

    key = _derive_fernet_key(passphrase, envelope.kdf)
    return Fernet(key).decrypt(envelope.ciphertext)


def _get_invalid_token_class() -> type[Exception]:
    """Lazy accessor for ``cryptography.fernet.InvalidToken``.

    Lets callers catch decryption failures without forcing
    ``cryptography`` to be importable at module load. Used by the
    :class:`EncryptedFileStorage` backend; not part of the
    user-facing surface.
    """
    from cryptography.fernet import InvalidToken

    return InvalidToken


def rotate_passphrase(
    envelope: Envelope,
    *,
    old_passphrase: str,
    new_passphrase: str,
    new_kdf: KdfParams | None = None,
) -> Envelope:
    """Re-encrypt the envelope's plaintext under a new passphrase.

    Generates a fresh salt by default (passing ``new_kdf`` overrides
    the KDF parameters as well). Sets ``rotated_at``. Useful for the
    F2.5 ``creds rotate`` CLI verb.
    """
    plaintext = decrypt(envelope, old_passphrase)
    fresh = encrypt(plaintext, new_passphrase, kdf=new_kdf)
    return replace(fresh, rotated_at=datetime.now(tz=UTC).isoformat())


__all__ = [
    "DEFAULT_ITERATIONS",
    "DEFAULT_LANES",
    "DEFAULT_MEMORY_COST_KIB",
    "ENVELOPE_VERSION",
    "Envelope",
    "KdfParams",
    "decrypt",
    "encrypt",
    "rotate_passphrase",
]


def __getattr__(name: str) -> object:
    """PEP 562 hook so ``from envelope import InvalidToken`` keeps working.

    Imports ``cryptography`` lazily on attribute access; raises a
    clean :class:`ImportError` (with the install hint) when the
    ``encrypted-store`` extra isn't installed.
    """
    if name == "InvalidToken":
        try:
            from cryptography.fernet import InvalidToken
        except ImportError as exc:
            msg = (
                "kaos_core.config.storage.envelope.InvalidToken requires the "
                "encrypted-store extra. Install kaos-core[encrypted-store]."
            )
            raise ImportError(msg) from exc
        return InvalidToken
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


# Importing os.urandom would be enough; we use ``secrets`` for
# clarity and explicit cryptographic-quality randomness. ``os`` is
# only here to make ``token_bytes`` and ``secrets.token_bytes``
# unambiguous in tooling that introspects this module.
_ = os.urandom
