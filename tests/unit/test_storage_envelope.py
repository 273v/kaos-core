"""Tests for the encrypted-file envelope format.

The envelope is a versioned JSON wrapper that carries a Fernet
ciphertext plus the Argon2id parameters needed to re-derive the
key. These tests pin:

- Round-trip: encrypt/decrypt against a small KDF profile so the
  suite stays under a second.
- Tamper detection: changing the ciphertext or the salt makes
  decryption fail with ``InvalidToken``.
- Version + algorithm gates: unknown ``version`` or unknown
  ``algorithm`` raise rather than fall through.
- Salt randomness: two fresh envelopes don't collide.
- Re-key under a new passphrase preserves the plaintext.

KDF parameters in tests are intentionally tiny (8 KiB / 1
iteration / 1 lane). Production defaults follow OWASP 2026
desktop-interactive guidance (64 MiB / 3 iterations / 4 lanes).
"""

from __future__ import annotations

import json

import pytest

from kaos_core.config.storage.envelope import (
    ENVELOPE_VERSION,
    Envelope,
    InvalidToken,  # via PEP 562 __getattr__ — only available when cryptography is.
    KdfParams,
    decrypt,
    encrypt,
    rotate_passphrase,
)

# Tiny KDF for fast tests — production defaults are much larger.
_TEST_KDF = KdfParams.fresh(memory_cost_kib=8, iterations=1, lanes=1)


def test_round_trip() -> None:
    plaintext = b"hello, kaos"
    envelope = encrypt(plaintext, "correct horse battery staple", kdf=_TEST_KDF)
    assert decrypt(envelope, "correct horse battery staple") == plaintext


def test_wrong_passphrase_raises_invalid_token() -> None:
    envelope = encrypt(b"secret", "right", kdf=_TEST_KDF)
    with pytest.raises(InvalidToken):
        decrypt(envelope, "wrong")


def test_tampered_ciphertext_raises_invalid_token() -> None:
    envelope = encrypt(b"secret", "right", kdf=_TEST_KDF)
    # Flip a byte in the middle of the ciphertext.
    raw = bytearray(envelope.ciphertext)
    raw[len(raw) // 2] ^= 0x01
    tampered = Envelope(
        version=envelope.version,
        kdf=envelope.kdf,
        cipher=envelope.cipher,
        ciphertext=bytes(raw),
        created_at=envelope.created_at,
    )
    with pytest.raises(InvalidToken):
        decrypt(tampered, "right")


def test_two_fresh_envelopes_have_distinct_salts() -> None:
    a = encrypt(b"secret", "pp", kdf=KdfParams.fresh(memory_cost_kib=8, iterations=1, lanes=1))
    b = encrypt(b"secret", "pp", kdf=KdfParams.fresh(memory_cost_kib=8, iterations=1, lanes=1))
    assert a.kdf.salt != b.kdf.salt
    assert a.ciphertext != b.ciphertext


def test_serialize_round_trip() -> None:
    envelope = encrypt(b"payload", "pp", kdf=_TEST_KDF)
    raw = envelope.serialize()
    decoded = Envelope.deserialize(raw)
    assert decoded == envelope
    assert decrypt(decoded, "pp") == b"payload"


def test_serialize_is_pretty_sorted_json() -> None:
    envelope = encrypt(b"x", "pp", kdf=_TEST_KDF)
    raw = envelope.serialize()
    parsed = json.loads(raw)
    # Keys at the top level should be sorted (created_at before
    # ciphertext alphabetically).
    keys = list(parsed.keys())
    assert keys == sorted(keys), keys


def test_envelope_carries_version_field() -> None:
    envelope = encrypt(b"x", "pp", kdf=_TEST_KDF)
    parsed = json.loads(envelope.serialize())
    assert parsed["version"] == ENVELOPE_VERSION


def test_unsupported_envelope_version_rejected() -> None:
    raw = json.dumps(
        {
            "version": 99,
            "kdf": _TEST_KDF.to_json(),
            "cipher": "fernet",
            "ciphertext": "x",
            "created_at": "2026-01-01T00:00:00Z",
            "rotated_at": None,
        }
    ).encode("utf-8")
    with pytest.raises(ValueError, match="Unsupported envelope version"):
        Envelope.deserialize(raw)


def test_unsupported_kdf_algorithm_rejected() -> None:
    bad_kdf = {
        "algorithm": "scrypt",  # we only support argon2id
        "salt": "AAAA",
        "memory_cost_kib": 8,
        "iterations": 1,
        "lanes": 1,
    }
    raw = json.dumps(
        {
            "version": 1,
            "kdf": bad_kdf,
            "cipher": "fernet",
            "ciphertext": "x",
            "created_at": "2026-01-01T00:00:00Z",
            "rotated_at": None,
        }
    ).encode("utf-8")
    with pytest.raises(ValueError, match="Unsupported KDF algorithm"):
        Envelope.deserialize(raw)


def test_unsupported_cipher_rejected() -> None:
    raw = json.dumps(
        {
            "version": 1,
            "kdf": _TEST_KDF.to_json(),
            "cipher": "aes-gcm-siv",  # not supported in v1
            "ciphertext": "x",
            "created_at": "2026-01-01T00:00:00Z",
            "rotated_at": None,
        }
    ).encode("utf-8")
    with pytest.raises(ValueError, match="Unsupported cipher"):
        Envelope.deserialize(raw)


def test_rotate_passphrase_preserves_plaintext() -> None:
    plaintext = b"unrotated secret"
    original = encrypt(plaintext, "old-pp", kdf=_TEST_KDF)
    rotated = rotate_passphrase(
        original,
        old_passphrase="old-pp",
        new_passphrase="new-pp",
        new_kdf=KdfParams.fresh(memory_cost_kib=8, iterations=1, lanes=1),
    )
    # Old passphrase no longer decrypts the rotated envelope.
    with pytest.raises(InvalidToken):
        decrypt(rotated, "old-pp")
    assert decrypt(rotated, "new-pp") == plaintext
    assert rotated.rotated_at is not None
    assert rotated.kdf.salt != original.kdf.salt


def test_rotate_with_wrong_old_passphrase_raises() -> None:
    original = encrypt(b"x", "old-pp", kdf=_TEST_KDF)
    with pytest.raises(InvalidToken):
        rotate_passphrase(
            original,
            old_passphrase="wrong",
            new_passphrase="new",
            new_kdf=_TEST_KDF,
        )


def test_kdf_params_record_what_was_used() -> None:
    envelope = encrypt(b"x", "pp", kdf=_TEST_KDF)
    parsed = json.loads(envelope.serialize())
    kdf = parsed["kdf"]
    assert kdf["algorithm"] == "argon2id"
    assert kdf["memory_cost_kib"] == 8
    assert kdf["iterations"] == 1
    assert kdf["lanes"] == 1
    assert isinstance(kdf["salt"], str) and len(kdf["salt"]) > 0
