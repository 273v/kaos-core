"""Cross-session VFS isolation tests.

Pins the security contract that the VFS admin tools (list, read, stat)
operate on the calling session's VFS namespace, not the shared default
scope. Previously these tools called ``runtime.vfs.list_page(path)``
without ``context_id``, so they read the unscoped default namespace
while ``context.get_vfs_path()`` writes through the session scope —
creating an isolation hole where a session's writes were invisible to
its own admin tools, and the shared default scope was reachable from
any session.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos_core import (
    KaosContext,
    KaosRuntime,
    StorageBackend,
    VFSConfig,
    VirtualFileSystem,
)
from kaos_core.tools import VFSListTool, VFSReadTool, VFSStatTool


@pytest.fixture
def runtime(tmp_path: Path) -> KaosRuntime:
    rt = KaosRuntime()
    rt.vfs = VirtualFileSystem(
        VFSConfig(default_backend=StorageBackend.DISK, disk_base_path=tmp_path / "vfs")
    )
    return rt


def _ctx(rt: KaosRuntime, session_id: str) -> KaosContext:
    return KaosContext.create(session_id=session_id, runtime=rt)


# ────────────────────────────────────────────────────────────────────
# VFSReadTool — sessions cannot read each other's writes
# ────────────────────────────────────────────────────────────────────


async def test_read_tool_cannot_see_other_session_files(runtime: KaosRuntime) -> None:
    # s1 writes "secret" into its own VFS namespace
    await runtime.vfs.write("secret.txt", b"s1 secret", context_id="s1")
    # s2 writes a different file into its own namespace
    await runtime.vfs.write("public.txt", b"s2 public", context_id="s2")

    tool = VFSReadTool()

    # s1 reads its own file successfully
    same_session = await tool.execute({"path": "secret.txt"}, context=_ctx(runtime, "s1"))
    assert not same_session.isError
    same_data = same_session.require_structured()
    assert same_data["content"] == "s1 secret"

    # s2 tries to read s1's file — must NOT find it
    cross_session = await tool.execute({"path": "secret.txt"}, context=_ctx(runtime, "s2"))
    assert cross_session.isError
    assert "not found" in (cross_session.text or "").lower()


# ────────────────────────────────────────────────────────────────────
# VFSStatTool — stat must be session-scoped
# ────────────────────────────────────────────────────────────────────


async def test_stat_tool_does_not_leak_other_session_existence(
    runtime: KaosRuntime,
) -> None:
    await runtime.vfs.write("only-s1.txt", b"x", context_id="s1")

    tool = VFSStatTool()

    # s1 sees its own file
    s1_result = await tool.execute({"path": "only-s1.txt"}, context=_ctx(runtime, "s1"))
    assert not s1_result.isError
    assert s1_result.require_structured()["exists"] is True

    # s2 stat-ing the same path must NOT see it (file does not exist
    # in s2's namespace)
    s2_result = await tool.execute({"path": "only-s1.txt"}, context=_ctx(runtime, "s2"))
    assert not s2_result.isError, "stat should succeed but report nonexistent"
    assert s2_result.require_structured()["exists"] is False


# ────────────────────────────────────────────────────────────────────
# VFSListTool — listing scoped to caller session
# ────────────────────────────────────────────────────────────────────


async def test_list_tool_only_lists_caller_session_files(runtime: KaosRuntime) -> None:
    await runtime.vfs.write("/s1-only.txt", b"x", context_id="s1")
    await runtime.vfs.write("/s2-only.txt", b"y", context_id="s2")

    tool = VFSListTool()

    s1_result = await tool.execute({"limit": 100}, context=_ctx(runtime, "s1"))
    s1_items = s1_result.require_structured()["items"]
    s1_names = {str(it) for it in s1_items}

    s2_result = await tool.execute({"limit": 100}, context=_ctx(runtime, "s2"))
    s2_items = s2_result.require_structured()["items"]
    s2_names = {str(it) for it in s2_items}

    # s1's listing mentions s1-only.txt, not s2-only.txt
    assert any("s1-only" in n for n in s1_names)
    assert not any("s2-only" in n for n in s1_names), (
        f"VFSListTool leaked s2's file into s1's listing: {s1_names}"
    )

    # And vice versa
    assert any("s2-only" in n for n in s2_names)
    assert not any("s1-only" in n for n in s2_names), (
        f"VFSListTool leaked s1's file into s2's listing: {s2_names}"
    )


# ────────────────────────────────────────────────────────────────────
# Default-scope writes are no longer reachable from a session via
# the VFS admin tools (they exist outside session scopes)
# ────────────────────────────────────────────────────────────────────


async def test_unscoped_default_writes_not_visible_via_session_tools(
    runtime: KaosRuntime,
) -> None:
    # Write to the shared default scope (no context_id provided).
    # This is what trusted in-process callers (cleanup, persistence)
    # use; it should NOT be reachable from session-scoped MCP tools.
    await runtime.vfs.write("/shared.txt", b"shared payload")

    read_result = await VFSReadTool().execute({"path": "shared.txt"}, context=_ctx(runtime, "s1"))
    assert read_result.isError
    assert "not found" in (read_result.text or "").lower()
