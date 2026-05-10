"""Tests for the F2.5 credential CLI verbs.

Each verb is exercised through ``main([...])`` so the argparse
plumbing and JSON-output contract are pinned alongside the
business logic. We use ``KAOS_STATE_DIR`` to keep the underlying
files in ``tmp_path``.
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from kaos_core.cli import main


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KAOS_STATE_DIR", str(tmp_path))
    # Force keyring tier off so tests don't accidentally write to a
    # real macOS Keychain or Windows Credential Manager.
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("KAOS_FORCE_KEYRING", raising=False)
    # Keep encrypted-file tier off too (no passphrase).
    monkeypatch.delenv("KAOS_PASSPHRASE", raising=False)


def _capture_json(capsys: pytest.CaptureFixture[str]) -> dict:
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_creds_tiers_reports_available_backends(capsys: pytest.CaptureFixture[str]) -> None:
    main(["creds", "tiers", "--json"])
    payload = _capture_json(capsys)
    assert payload["command"] == "creds tiers"
    assert payload["active_tier"] == "PLAINTEXT"
    tiers = {t["tier"]: t for t in payload["tiers"]}
    assert tiers["PLAINTEXT"]["available"] is True


def test_creds_set_reads_from_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", StringIO("sk-test-value\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    main(["creds", "set", "kaos-llm", "openai", "--json"])
    payload = _capture_json(capsys)
    assert payload["command"] == "creds set"
    assert payload["module"] == "kaos-llm"
    assert payload["service"] == "openai"
    assert payload["key"] == "default"
    assert payload["tier"] == "PLAINTEXT"


def test_creds_set_then_list(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", StringIO("v1"))
    main(["creds", "set", "kaos-llm", "openai"])
    capsys.readouterr()  # discard set output

    main(["creds", "list", "--module", "kaos-llm", "--json"])
    payload = _capture_json(capsys)
    services = [c["service"] for c in payload["credentials"]]
    assert "openai" in services


def test_creds_set_empty_value_aborts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", StringIO("\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit):
        main(["creds", "set", "kaos-llm", "openai"])
    captured = capsys.readouterr()
    assert "empty value" in captured.err


def test_creds_delete_removes_from_storage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # First set a value...
    monkeypatch.setattr("sys.stdin", StringIO("v1"))
    main(["creds", "set", "kaos-llm", "openai"])
    capsys.readouterr()
    # ... then delete it.
    main(["creds", "delete", "kaos-llm", "openai", "--json"])
    payload = _capture_json(capsys)
    assert payload["command"] == "creds delete"
    # And it shouldn't appear in the listing.
    main(["creds", "list", "--module", "kaos-llm", "--json"])
    payload = _capture_json(capsys)
    services = [c["service"] for c in payload["credentials"]]
    assert "openai" not in services


def test_creds_migrate_dry_run_does_not_move(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", StringIO("v1"))
    main(["creds", "set", "kaos-llm", "openai"])
    capsys.readouterr()
    # Only plaintext tier is available in the test environment, so
    # migrate has nowhere stronger to go. Even so, the dry-run JSON
    # must report a sensible (empty) outcome.
    main(["creds", "migrate", "--dry-run", "--json"])
    payload = _capture_json(capsys)
    assert payload["command"] == "creds migrate"
    assert payload["dry_run"] is True
    # When only the plaintext floor is available, migrate sees the
    # value is already at strongest available and reports it as
    # "already at PLAINTEXT" — encoded as moved=[..., tier=PLAINTEXT].
    assert all(row["tier"] == "PLAINTEXT" for row in payload["moved"])


def test_creds_human_readable_tiers(capsys: pytest.CaptureFixture[str]) -> None:
    main(["creds", "tiers"])
    captured = capsys.readouterr().out
    assert "Active tier: PLAINTEXT" in captured
    assert "PLAINTEXT" in captured
    assert "PlaintextStorage" in captured


def test_auth_status_empty_environment(capsys: pytest.CaptureFixture[str]) -> None:
    main(["auth", "status", "--json"])
    payload = _capture_json(capsys)
    assert payload["command"] == "auth status"
    assert payload["count"] == 0
    assert payload["entries"] == []


def test_auth_status_human_readable(capsys: pytest.CaptureFixture[str]) -> None:
    main(["auth", "status"])
    captured = capsys.readouterr().out
    assert "(no stored OAuth tokens detected)" in captured
