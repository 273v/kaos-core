"""Tests for kaos-core CLI."""

from __future__ import annotations

import asyncio
import json
from io import StringIO
from unittest.mock import patch

import pytest

from kaos_core.cli import main
from kaos_core.registry import KaosRuntime

# ---------------------------------------------------------------------------
# tools list
# ---------------------------------------------------------------------------


class TestToolsList:
    """Tests for 'tools list' command."""

    def test_tools_list_human(self) -> None:
        """Human output runs without error (may be empty)."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["tools", "list"])
        output = stdout.getvalue()
        # Empty registry says "No tools registered."
        assert "No tools" in output or "Name" in output

    def test_tools_list_json(self) -> None:
        """JSON output has correct envelope."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["tools", "list", "--json"])
        data = json.loads(stdout.getvalue())
        assert data["command"] == "tools list"
        assert "total" in data
        assert isinstance(data["total"], int)
        assert "tools" in data
        assert isinstance(data["tools"], list)

    def test_tools_list_json_structure(self) -> None:
        """JSON total matches tools list length."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["tools", "list", "--json"])
        data = json.loads(stdout.getvalue())
        assert data["total"] == len(data["tools"])
        assert isinstance(data["total"], int)
        assert data["total"] >= 0


# ---------------------------------------------------------------------------
# tools search
# ---------------------------------------------------------------------------


class TestToolsSearch:
    """Tests for 'tools search' command."""

    def test_tools_search_human(self) -> None:
        """Human search output runs without error."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["tools", "search", "something"])
        output = stdout.getvalue()
        assert "No tools" in output or "Name" in output

    def test_tools_search_json(self) -> None:
        """JSON search output has correct envelope."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["tools", "search", "test-query", "--json"])
        data = json.loads(stdout.getvalue())
        assert data["command"] == "tools search"
        assert data["query"] == "test-query"
        assert "total" in data
        assert isinstance(data["tools"], list)

    def test_tools_search_invalid_category(self) -> None:
        """Invalid category exits with error."""
        with pytest.raises(SystemExit) as exc_info:
            main(["tools", "search", "query", "--category", "nonexistent"])
        assert exc_info.value.code != 0

    def test_tools_search_invalid_capability(self) -> None:
        """Invalid capability exits with error."""
        with pytest.raises(SystemExit) as exc_info:
            main(["tools", "search", "query", "--capability", "nonexistent"])
        assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# artifacts list
# ---------------------------------------------------------------------------


class TestArtifactsList:
    """Tests for 'artifacts list' command."""

    def test_artifacts_list_human(self) -> None:
        """Human output runs without error."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["artifacts", "list"])
        output = stdout.getvalue()
        assert "No artifacts" in output or "ID" in output

    def test_artifacts_list_json(self) -> None:
        """JSON output has correct envelope."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["artifacts", "list", "--json"])
        data = json.loads(stdout.getvalue())
        assert data["command"] == "artifacts list"
        assert "total" in data
        assert isinstance(data["artifacts"], list)

    def test_artifacts_list_json_with_session(self) -> None:
        """Session filter is accepted."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["artifacts", "list", "--session", "test-session-123", "--json"])
        data = json.loads(stdout.getvalue())
        assert data["command"] == "artifacts list"
        assert data["total"] == 0


# ---------------------------------------------------------------------------
# config show
# ---------------------------------------------------------------------------


class TestConfigShow:
    """Tests for 'config show' command."""

    def test_config_show_human(self) -> None:
        """Human output shows key-value pairs."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["config", "show"])
        output = stdout.getvalue()
        # Should contain known settings keys
        assert "log_level" in output
        assert "timeout" in output

    def test_config_show_json(self) -> None:
        """JSON output has correct envelope and settings."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["config", "show", "--json"])
        data = json.loads(stdout.getvalue())
        assert data["command"] == "config show"
        assert "log_level" in data
        assert "timeout" in data
        assert "cache_enabled" in data


# ---------------------------------------------------------------------------
# vfs ls
# ---------------------------------------------------------------------------


class TestVfsLs:
    """Tests for 'vfs ls' command."""

    def test_vfs_ls_human(self) -> None:
        """Human output runs without error."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["vfs", "ls"])
        output = stdout.getvalue()
        # May be empty or have items
        assert "No items" in output or len(output.strip()) >= 0

    def test_vfs_ls_json(self) -> None:
        """JSON output has correct envelope."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["vfs", "ls", "--json"])
        data = json.loads(stdout.getvalue())
        assert data["command"] == "vfs ls"
        assert "path" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_vfs_ls_with_path(self) -> None:
        """Path argument is accepted."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["vfs", "ls", "some/path", "--json"])
        data = json.loads(stdout.getvalue())
        assert data["command"] == "vfs ls"
        assert data["path"] == "some/path"

    def test_vfs_ls_default_path_json(self) -> None:
        """Default path shows '/' in JSON output."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["vfs", "ls", "--json"])
        data = json.loads(stdout.getvalue())
        assert data["path"] == "/"

    def test_vfs_ls_accepts_cursor(self, runtime: KaosRuntime) -> None:
        for index in range(101):
            asyncio.run(runtime.vfs.write(f"item-{index:03}.txt", b"x"))

        stdout = StringIO()
        with patch("sys.stdout", stdout):
            main(["vfs", "ls", "--cursor", "100", "--json"])
        data = json.loads(stdout.getvalue())
        assert data["command"] == "vfs ls"
        assert data["cursor"] == "100"
        assert data["items"] == ["item-100.txt"]
        assert data["next_cursor"] is None


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    """Tests for error handling."""

    def test_missing_command(self) -> None:
        """Missing command exits with error."""
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0

    def test_missing_action(self) -> None:
        """Missing action exits with error."""
        with pytest.raises(SystemExit) as exc_info:
            main(["tools"])
        assert exc_info.value.code != 0

    def test_missing_action_artifacts(self) -> None:
        """Missing action for artifacts exits with error."""
        with pytest.raises(SystemExit) as exc_info:
            main(["artifacts"])
        assert exc_info.value.code != 0

    def test_missing_action_config(self) -> None:
        """Missing action for config exits with error."""
        with pytest.raises(SystemExit) as exc_info:
            main(["config"])
        assert exc_info.value.code != 0

    def test_missing_action_vfs(self) -> None:
        """Missing action for vfs exits with error."""
        with pytest.raises(SystemExit) as exc_info:
            main(["vfs"])
        assert exc_info.value.code != 0

    def test_unknown_command(self) -> None:
        """Unknown command exits with error."""
        with pytest.raises(SystemExit) as exc_info:
            main(["nonexistent"])
        assert exc_info.value.code != 0

    def test_version(self) -> None:
        """--version flag works."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
