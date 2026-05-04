"""Tests for the CredentialStore disk hardening contract.

These tests pin the contract documented in ``CredentialStore``'s
docstring: file mode ``0o600`` after every write, atomic replace via a
sibling temp file, no plaintext orphan after a successful write.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from kaos_core.config.credentials import CredentialStore


def test_set_writes_file_with_mode_0600(tmp_path: Path) -> None:
    target = tmp_path / "creds.json"
    store = CredentialStore(target)
    store.set("kaos-llm", "openai", "default", "sk-test")

    assert target.exists()
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_set_overwrite_preserves_mode_0600(tmp_path: Path) -> None:
    target = tmp_path / "creds.json"
    store = CredentialStore(target)
    store.set("kaos-llm", "openai", "default", "sk-test-1")
    # An overwrite goes through the same atomic-replace path.
    store.set("kaos-llm", "openai", "default", "sk-test-2")

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


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
    mode = stat.S_IMODE(nested.stat().st_mode)
    assert mode == 0o600


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
    # Mode must still be 0o600 after delete.
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_directory_is_writable_only_by_owner(tmp_path: Path) -> None:
    """Sanity check that pytest's tmp_path inherits umask but the file mode
    we set is independent of the parent directory's mode."""
    target = tmp_path / "creds.json"
    store = CredentialStore(target)
    store.set("m", "s", "k", "v")

    # The file we wrote is 0o600; the parent dir is whatever pytest gave us.
    file_mode = stat.S_IMODE(target.stat().st_mode)
    assert file_mode == 0o600
    # And the file is readable by the owner...
    assert os.access(target, os.R_OK)
    # ...but the mode bits explicitly do not grant group/other read.
    assert not (file_mode & (stat.S_IRGRP | stat.S_IROTH))
    assert not (file_mode & (stat.S_IWGRP | stat.S_IWOTH))
