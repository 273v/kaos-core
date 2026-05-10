"""Pin the VFS path-string contract: every external path string is
forward-slash separated on every OS.

Before F1.2, ``DiskBackend.list()`` used ``str(child.relative_to(...))``
which renders with the native separator (backslash on Windows), so the
internal forward-slash prefix comparisons never matched and the method
returned ``[]``. That cascaded into ``walk``, ``list_page``,
``cleanup_context``, ``VFSPath.iterdir``, and the VFS list-tool.

This module is the regression net for the contract: regardless of how
the underlying filesystem natively spells separators, our list/stat/
iterdir surface MUST emit forward-slash form.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos_core.vfs.backends import DiskBackend


@pytest.mark.asyncio
async def test_disk_backend_list_returns_posix_separators(tmp_path: Path) -> None:
    backend = DiskBackend(tmp_path)
    await backend.write("a/b/c.txt", b"x")
    await backend.write("a/d.txt", b"y")
    await backend.write("e/f.txt", b"z")

    items_all = await backend.list("")
    assert items_all == ["a/b/c.txt", "a/d.txt", "e/f.txt"]
    assert all("\\" not in p for p in items_all), items_all


@pytest.mark.asyncio
async def test_disk_backend_list_prefix_matches_after_nested_write(tmp_path: Path) -> None:
    """The bug surface: prefix-listing with nested children. On Windows
    pre-F1.2, ``list('logs')`` returned ``[]`` here because the entries
    came back as ``logs\\output.txt`` and never matched the forward-slash
    prefix."""
    backend = DiskBackend(tmp_path)
    await backend.write("logs/output.txt", b"x")
    await backend.write("logs/nested/inner.txt", b"y")
    await backend.write("other/file.txt", b"z")

    assert await backend.list("logs") == ["logs/nested/inner.txt", "logs/output.txt"]
    assert await backend.list("logs/nested") == ["logs/nested/inner.txt"]


@pytest.mark.asyncio
async def test_disk_backend_list_single_file_match(tmp_path: Path) -> None:
    backend = DiskBackend(tmp_path)
    await backend.write("a/b/c.txt", b"hello")
    # Exact-path prefix matches the file itself.
    assert await backend.list("a/b/c.txt") == ["a/b/c.txt"]


@pytest.mark.asyncio
async def test_disk_backend_list_empty_for_missing_prefix(tmp_path: Path) -> None:
    backend = DiskBackend(tmp_path)
    await backend.write("a/file.txt", b"x")
    assert await backend.list("nonexistent") == []
