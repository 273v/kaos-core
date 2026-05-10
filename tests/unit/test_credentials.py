"""Tests for the CredentialStore disk-hardening contract.

These tests pin the contract documented in ``CredentialStore``'s
docstring: after every write, the file is restricted to owner-only
access via the platform's native primitive (``chmod 0o600`` on POSIX,
NTFS DACL via ``pywin32`` on Windows), atomic replace via a sibling
temp file, and no plaintext orphan after a successful write.

The owner-only assertion is delegated to ``_assert_owner_only`` so
each test reads naturally on every platform; the helper checks mode
bits on POSIX and inspects the DACL on Windows when ``pywin32`` is
available.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from kaos_core.config.credentials import CredentialStore


def _windows_dacl_grants_only_current_user(path: Path) -> bool | None:
    """Return True if *path*'s DACL grants ALLOWED access only to the
    current user, False if other principals are also granted access,
    None if pywin32 isn't installed (caller should skip the check).
    """
    try:
        import win32security  # ty: ignore[unresolved-import]
    except ImportError:
        return None

    current_user_sid, _, _ = win32security.LookupAccountName("", win32security.GetUserName())
    descriptor = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
    dacl = descriptor.GetSecurityDescriptorDacl()
    if dacl is None:
        # No DACL set means "grant everyone access" on Windows; that's
        # exactly what we're trying to prevent.
        return False

    ace_count = dacl.GetAceCount()
    for i in range(ace_count):
        ace = dacl.GetAce(i)
        # ace = ((ace_type, ace_flags), access_mask, sid)
        ace_type = ace[0][0]
        ace_sid = ace[2]
        # ACCESS_ALLOWED_ACE_TYPE == 0; we only check allow-grants.
        if ace_type != 0:
            continue
        if ace_sid != current_user_sid:
            return False
    return True


def _assert_owner_only(path: Path) -> None:
    """Assert *path* is restricted to the current user via the native primitive.

    POSIX: ``stat().st_mode & 0o777 == 0o600``.
    Windows: DACL contains only ALLOWED-ACE entries for the current
             user. If ``pywin32`` isn't installed (the
             ``kaos-core[windows-secure]`` extra wasn't selected), the
             check is skipped — the library logs a warning in that
             case and the credentials file is NOT actually hardened.
             That's a documented degradation; the test's job here is
             to verify hardening works WHEN supported, not to enforce
             it on environments that opted out.
    """
    if sys.platform == "win32":
        result = _windows_dacl_grants_only_current_user(path)
        if result is None:
            pytest.skip(
                "pywin32 not installed; install kaos-core[windows-secure] "
                "to exercise the NTFS ACL hardening path",
            )
        assert result, (
            f"NTFS DACL on {path} grants access to principals other than the current user"
        )
    else:
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_set_writes_file_with_owner_only_access(tmp_path: Path) -> None:
    target = tmp_path / "creds.json"
    store = CredentialStore(target)
    store.set("kaos-llm", "openai", "default", "sk-test")

    assert target.exists()
    _assert_owner_only(target)


def test_set_overwrite_preserves_owner_only_access(tmp_path: Path) -> None:
    target = tmp_path / "creds.json"
    store = CredentialStore(target)
    store.set("kaos-llm", "openai", "default", "sk-test-1")
    # An overwrite goes through the same atomic-replace path.
    store.set("kaos-llm", "openai", "default", "sk-test-2")

    _assert_owner_only(target)


def test_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "creds.json"
    store = CredentialStore(target)
    store.set("kaos-llm", "openai", "default", "sk-test")
    store.set("kaos-llm", "anthropic", "default", "sk-ant-test")
    store.delete("kaos-llm", "openai", "default")

    # Only the target file should remain; no .tmp-* siblings left behind.
    siblings = sorted(p.name for p in tmp_path.iterdir())
    assert siblings == ["creds.json"], f"unexpected leftover files: {siblings}"


def test_set_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "deeper" / "creds.json"
    store = CredentialStore(nested)
    store.set("kaos-llm", "openai", "default", "sk-test")

    assert nested.exists()
    _assert_owner_only(nested)


def test_round_trip_set_get_delete(tmp_path: Path) -> None:
    target = tmp_path / "creds.json"
    store = CredentialStore(target)

    store.set("kaos-llm", "openai", "default", "sk-test")
    store.set("kaos-llm", "anthropic", "default", "sk-ant-test")
    store.set("kaos-source", "govinfo", "default", "gi-test")

    assert store.get("kaos-llm", "openai", "default") == "sk-test"
    assert store.get("kaos-llm", "anthropic", "default") == "sk-ant-test"
    assert store.get("kaos-source", "govinfo", "default") == "gi-test"
    assert store.get("kaos-llm", "missing") is None

    assert store.list_services("kaos-llm") == ["anthropic", "openai"]
    assert store.list_services("nonexistent") == []

    store.delete("kaos-llm", "openai", "default")
    assert store.get("kaos-llm", "openai", "default") is None
    # Owner-only restriction must still hold after delete.
    _assert_owner_only(target)


def test_owner_can_read_file(tmp_path: Path) -> None:
    """Sanity check that hardening doesn't lock the owner out."""
    target = tmp_path / "creds.json"
    store = CredentialStore(target)
    store.set("m", "s", "k", "v")

    # Owner can read on every platform.
    assert os.access(target, os.R_OK)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits aren't enforced on NTFS")
def test_posix_mode_excludes_group_and_other(tmp_path: Path) -> None:
    """POSIX-specific: 0o600 explicitly denies group/other read/write."""
    target = tmp_path / "creds.json"
    store = CredentialStore(target)
    store.set("m", "s", "k", "v")

    file_mode = stat.S_IMODE(target.stat().st_mode)
    assert not (file_mode & (stat.S_IRGRP | stat.S_IROTH))
    assert not (file_mode & (stat.S_IWGRP | stat.S_IWOTH))
