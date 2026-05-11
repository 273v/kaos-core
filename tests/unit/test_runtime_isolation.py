"""Unit tests for :class:`KaosRuntime` VFS-isolation primitives.

These cover the Sprint-1 hardening that closed the
"silently false-greens live composition tests on 2nd-run" hazard:

1. ``KaosRuntime(vfs=...)`` accepts and uses an injected VFS.
2. ``KaosRuntime.test_mode()`` returns an instance with an in-memory,
   globally scoped VFS.
3. ``runtime.artifacts`` is a :class:`cached_property` over
   ``self.vfs``. Replacing ``runtime.vfs`` invalidates the cache so
   ``runtime.artifacts._vfs`` is always the live VFS.
4. Cross-run leakage regression: a default ``KaosRuntime()`` writes to
   the disk-backed ``.kaos-vfs`` and the bytes survive a second
   ``KaosRuntime()`` (simulating a second pytest invocation), whereas
   ``KaosRuntime.test_mode()`` is fully isolated.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kaos_core import KaosRuntime, VFSConfig, VirtualFileSystem
from kaos_core.types.enums import IsolationMode, StorageBackend


def test_runtime_accepts_injected_vfs() -> None:
    """``KaosRuntime(vfs=...)`` short-circuits the default disk-backed VFS."""

    injected = VirtualFileSystem(
        config=VFSConfig(
            default_backend=StorageBackend.MEMORY,
            isolation_mode=IsolationMode.GLOBAL,
        )
    )
    runtime = KaosRuntime(vfs=injected)

    assert runtime.vfs is injected
    # ArtifactStore must point at the same VFS — no construction-time
    # capture of a different instance.
    assert runtime.artifacts._vfs is injected


def test_test_mode_returns_in_memory_runtime() -> None:
    """``test_mode()`` defaults to in-memory + GLOBAL isolation."""

    runtime = KaosRuntime.test_mode()
    assert runtime.vfs.config.default_backend is StorageBackend.MEMORY
    assert runtime.vfs.config.isolation_mode is IsolationMode.GLOBAL
    assert runtime.artifacts._vfs is runtime.vfs


def test_test_mode_disk_form_still_isolated_global() -> None:
    """``test_mode(in_memory=False)`` keeps the GLOBAL isolation
    guarantee (just on a disk backend) so disk-backed integration
    tests can opt out of the per-context default."""

    runtime = KaosRuntime.test_mode(in_memory=False)
    assert runtime.vfs.config.default_backend is StorageBackend.DISK
    assert runtime.vfs.config.isolation_mode is IsolationMode.GLOBAL


def test_artifacts_is_lazy_over_vfs() -> None:
    """Replacing ``runtime.vfs`` invalidates the cached
    ``artifacts`` and the next read rebuilds against the new VFS.
    This is the post-init footgun the cached_property closes.
    """

    runtime = KaosRuntime.test_mode()
    original_artifacts = runtime.artifacts
    original_vfs = runtime.vfs

    replacement = VirtualFileSystem(
        config=VFSConfig(
            default_backend=StorageBackend.MEMORY,
            isolation_mode=IsolationMode.GLOBAL,
        )
    )
    runtime.vfs = replacement

    # The cache is invalidated — next access returns a fresh store
    # bound to the new VFS.
    assert runtime.vfs is replacement
    assert runtime.vfs is not original_vfs
    new_artifacts = runtime.artifacts
    assert new_artifacts is not original_artifacts
    assert new_artifacts._vfs is replacement


def test_artifacts_cached_within_same_vfs() -> None:
    """Two reads without a VFS swap return the same instance — the
    property is cached, not rebuilt on every read."""

    runtime = KaosRuntime.test_mode()
    assert runtime.artifacts is runtime.artifacts


def test_default_runtime_disk_leaks_across_constructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Regression**: the default ``KaosRuntime()`` uses
    :attr:`StorageBackend.DISK` and writes survive across runtime
    instances — that's the cross-run leakage that false-greened live
    tests on re-run.
    """

    # Point the disk VFS at a per-test temp directory so we don't
    # collide with the real ``.kaos-vfs``.
    vfs_root = tmp_path / "kaos-vfs"
    monkeypatch.chdir(tmp_path)

    runtime_a = KaosRuntime()
    # Force the disk backend to write under tmp_path. The default
    # ``VFSConfig.disk_base_path`` is the relative ``.kaos-vfs``,
    # which monkeypatch.chdir() above redirects to tmp_path.
    runtime_a.vfs.config.disk_base_path = vfs_root

    import asyncio

    async def write_then_read() -> bytes:
        await runtime_a.vfs.write("isolation-probe.bin", b"payload-a", context_id="probe")
        # Simulate a second pytest invocation: throw away runtime_a,
        # spin up a fresh one against the same base path.
        runtime_b = KaosRuntime()
        runtime_b.vfs.config.disk_base_path = vfs_root
        return await runtime_b.vfs.read("isolation-probe.bin", context_id="probe")

    leaked = asyncio.run(write_then_read())
    assert leaked == b"payload-a", (
        "Sanity check: the default disk-backed VFS is supposed to "
        "persist across runtime instances. If this assertion fails, "
        "either the leakage hazard was already fixed elsewhere or "
        "the test setup is wrong."
    )
    # Clean up so we don't pollute the developer's working tree.
    shutil.rmtree(vfs_root, ignore_errors=True)


def test_test_mode_does_not_leak_across_constructions() -> None:
    """``KaosRuntime.test_mode()`` does NOT leak across runtime
    instances — each one gets a fresh in-memory backend. This is the
    paired half of the regression above.
    """

    import asyncio

    async def write_then_attempt_read() -> bool:
        runtime_a = KaosRuntime.test_mode()
        await runtime_a.vfs.write("isolation-probe.bin", b"payload-a", context_id="probe")

        runtime_b = KaosRuntime.test_mode()
        # Different in-memory backend instance — the bytes from
        # runtime_a must NOT be visible.
        return await runtime_b.vfs.exists("isolation-probe.bin", context_id="probe")

    assert asyncio.run(write_then_attempt_read()) is False, (
        "test_mode() leaked memory across runtime instances — the "
        "isolation guarantee is broken. Live composition tests will "
        "false-green on re-run."
    )
