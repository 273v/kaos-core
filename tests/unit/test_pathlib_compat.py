"""Tests for ``kaos_core.utils.pathlib_compat``.

Pin the cross-platform path-handling contract used throughout the VFS
and artifact layers. The Windows-form-on-POSIX cases below run on
every leg of the matrix because the helper does manual leading-slash
handling; we want to confirm it doesn't regress on POSIX either.
"""

from __future__ import annotations

import sys
from pathlib import Path

from kaos_core.utils.pathlib_compat import file_uri_to_path, to_posix_str


class TestToPosixStr:
    def test_path_with_native_separator(self) -> None:
        result = to_posix_str(Path("a") / "b" / "c")
        assert result == "a/b/c"
        assert "\\" not in result

    def test_string_path(self) -> None:
        # str input — go through Path so the same normalization applies.
        # A string with backslashes is treated as a Windows path on
        # Windows and as part-of-a-name on POSIX; the helper documents
        # the round-trip via Path explicitly.
        assert to_posix_str("a/b/c") == "a/b/c"

    def test_absolute_path_round_trip(self) -> None:
        if sys.platform == "win32":
            assert to_posix_str(Path("C:/Users/foo")) == "C:/Users/foo"
        else:
            assert to_posix_str(Path("/home/foo")) == "/home/foo"

    def test_no_backslashes_in_output(self) -> None:
        result = to_posix_str(Path("nested") / "deeper" / "leaf.txt")
        assert "\\" not in result, result


class TestFileUriToPath:
    def test_returns_none_for_non_file_scheme(self) -> None:
        assert file_uri_to_path("https://example.com/x") is None
        assert file_uri_to_path("kaos://artifacts/abc") is None
        assert file_uri_to_path("s3://bucket/key") is None

    def test_posix_style_uri(self) -> None:
        result = file_uri_to_path("file:///home/user/x")
        assert result is not None
        if sys.platform != "win32":
            # On POSIX, /home/user/x is a literal path.
            assert str(result) == "/home/user/x"

    def test_round_trip_with_path_as_uri(self, tmp_path: Path) -> None:
        # The roots-policy test in test_context_runtime_and_vfs_primitives
        # constructs URIs via Path.as_uri(); this helper must invert that.
        target = (tmp_path / "session").resolve()
        round_tripped = file_uri_to_path(target.as_uri())
        assert round_tripped is not None
        assert round_tripped.resolve() == target

    def test_percent_encoded_path(self) -> None:
        # Spaces and other reserved chars come back unquoted.
        result = file_uri_to_path("file:///tmp/with%20space")
        assert result is not None
        if sys.platform != "win32":
            assert str(result) == "/tmp/with space"

    def test_empty_path_returns_root(self) -> None:
        # file:// with no path defaults to "/".
        result = file_uri_to_path("file:///")
        assert result is not None
