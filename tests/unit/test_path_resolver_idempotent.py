"""Idempotency tests for ``path_resolver._resolve`` (plan §Issue 7 / #582).

Plan §Issue 7 acceptance row:

    #582 — kaos-core ``path_resolver._resolve`` non-idempotently
    prepends ``default_vfs_namespace``. Path doubles to
    ``sessions/{sid}/files/sessions/{sid}/files/{name}``. Fix:
    "Idempotency check: ``if namespace and not stripped.startswith(
    namespace): vfs_lookup = namespace + stripped``".

These tests pin the post-fix contract: calling ``resolve_input_path``
on the same logical file via two equivalent inputs (a bare name and
its namespaced form) produces the same resolved content, with no
``files/files/`` double-prefix.

The fix is load-bearing — the 2026-05-17 NDA verification matrix
had a P0 where every uploaded NDA returned "not found" because the
SPA passed ``files/EMNA.docx`` to the resolver, which then prepended
its own ``files/`` to produce ``files/files/EMNA.docx``. Without
this idempotency check, SPA + agent hygiene drift silently breaks
every corpus tool.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from kaos_core import (
    ArtifactStore,
    KaosContext,
    KaosRuntime,
    KaosSettings,
    VFSConfig,
    VirtualFileSystem,
)
from kaos_core.path_resolver import ResolvedOrigin, resolve_input_path
from kaos_core.types.enums import StorageBackend


def _make_runtime(tmp_path: Path) -> KaosRuntime:
    """Disk-backed VFS rooted in ``tmp_path`` — mirrors the canonical
    test_path_resolver.py fixture so the namespace-prepend code path
    exercises the real disk-backed lookup."""
    settings = KaosSettings(
        artifact_inline_read_max_bytes=262_144,
        artifact_chunk_size_bytes=64,
    )
    runtime = KaosRuntime(config=settings)
    runtime.vfs = VirtualFileSystem(
        VFSConfig(default_backend=StorageBackend.DISK, disk_base_path=tmp_path / "vfs"),
    )
    runtime.artifacts = ArtifactStore(
        runtime.vfs,
        manifest_context_id=settings.artifact_manifest_context_id,
        manifest_prefix=settings.artifact_manifest_prefix,
        max_inline_read_bytes=settings.artifact_inline_read_max_bytes,
        default_chunk_size=settings.artifact_chunk_size_bytes,
        temporary_ttl_seconds=settings.artifact_temporary_ttl_seconds,
    )
    return runtime


@pytest.fixture
def runtime(tmp_path: Path) -> Iterator[KaosRuntime]:
    yield _make_runtime(tmp_path)


# ── The plan-acceptance fixture ─────────────────────────────────────


@pytest.mark.asyncio
async def test_bare_name_and_namespaced_name_resolve_to_same_content(
    runtime: KaosRuntime,
) -> None:
    """Plan §Issue 7 / #582 verbatim: passing ``files/contract.docx``
    when the default namespace is ``files/`` MUST NOT double-prefix
    to ``files/files/contract.docx``. Both the bare and the already-
    namespaced form must resolve to the same file."""
    ctx = KaosContext(
        session_id="s-issue-7",
        runtime=runtime,
        vfs=runtime.vfs,
        default_vfs_namespace="files/",
    )
    payload = b"PK\x03\x04-fake-docx-body"
    # Write the file ONCE at the canonical location.
    handle = ctx.get_vfs_path("files/contract.docx")
    await handle.write_bytes(payload)

    # Bare name resolves via the namespace prepend (the existing
    # 0.1.0a10 contract).
    async with resolve_input_path("contract.docx", context=ctx) as r1:
        assert r1.origin is ResolvedOrigin.VFS
        assert r1.path.read_bytes() == payload

    # Already-namespaced name MUST resolve to the SAME content —
    # not "files/files/contract.docx" not found.
    async with resolve_input_path("files/contract.docx", context=ctx) as r2:
        assert r2.origin is ResolvedOrigin.VFS
        assert r2.path.read_bytes() == payload


@pytest.mark.asyncio
async def test_double_prefix_does_not_occur_in_resolved_path(
    runtime: KaosRuntime,
) -> None:
    """Defense-in-depth: when the caller passes the already-namespaced
    form, the resolved internal VFS lookup MUST NOT contain the
    namespace twice anywhere. A future "smarter" rewrite that
    re-introduces the double-prefix should fail loudly via this
    test."""
    ctx = KaosContext(
        session_id="s-double-prefix",
        runtime=runtime,
        vfs=runtime.vfs,
        default_vfs_namespace="files/",
    )
    handle = ctx.get_vfs_path("files/a.txt")
    await handle.write_bytes(b"hello")

    async with resolve_input_path("files/a.txt", context=ctx) as resolved:
        assert resolved.origin is ResolvedOrigin.VFS
        # The resolved path should reach the file. If a future
        # regression re-introduces double-prefix, this read will
        # raise FileNotFoundError.
        assert resolved.path.read_bytes() == b"hello"


# ── No-op case: empty namespace is unaffected by the fix ───────────


@pytest.mark.asyncio
async def test_empty_namespace_passes_bare_path_through(
    runtime: KaosRuntime,
) -> None:
    """When ``default_vfs_namespace`` is empty, the resolver passes
    the path through unchanged. The idempotency fix is namespace-
    gated and must not regress this case."""
    ctx = KaosContext(
        session_id="s-no-namespace",
        runtime=runtime,
        vfs=runtime.vfs,
        default_vfs_namespace="",
    )
    handle = ctx.get_vfs_path("data/x.json")
    await handle.write_bytes(b"{}")

    async with resolve_input_path("data/x.json", context=ctx) as resolved:
        assert resolved.origin is ResolvedOrigin.VFS
        assert resolved.path.read_bytes() == b"{}"


# ── Cross-namespace string match is NOT mistaken for prefix ────────


@pytest.mark.asyncio
async def test_partial_namespace_overlap_does_not_match(
    runtime: KaosRuntime,
) -> None:
    """A file named ``filesystem-report.txt`` shares a prefix with
    the namespace ``files/`` but is NOT under it; the resolver must
    treat that as a bare name (prepend namespace once) rather than
    "already namespaced". ``startswith("files/")`` is the exact
    check — ``startswith("files")`` would be a bug."""
    ctx = KaosContext(
        session_id="s-overlap",
        runtime=runtime,
        vfs=runtime.vfs,
        default_vfs_namespace="files/",
    )
    # Write at the "files/" canonical location.
    handle = ctx.get_vfs_path("files/filesystem-report.txt")
    await handle.write_bytes(b"report body")

    # Caller passes the bare form (no slash). The namespace is
    # prepended exactly once.
    async with resolve_input_path("filesystem-report.txt", context=ctx) as resolved:
        assert resolved.origin is ResolvedOrigin.VFS
        assert resolved.path.read_bytes() == b"report body"


# ── Deeper-nested namespace (matters/) also idempotent ─────────────


@pytest.mark.asyncio
async def test_idempotent_for_multi_segment_namespace(
    runtime: KaosRuntime,
) -> None:
    """Plan §Issue 2 wires the per-matter namespace
    ``matters/{mid}/sessions/{sid}/files/``. The idempotency fix must
    work for any namespace shape, not just ``files/`` — assert this
    with a 4-segment namespace so a future shorter-prefix-only
    optimisation can't regress the multi-tenant case."""
    namespace = "matters/abc-2026-0042/sessions/s-1/files/"
    ctx = KaosContext(
        session_id="s-multi-namespace",
        runtime=runtime,
        vfs=runtime.vfs,
        default_vfs_namespace=namespace,
    )
    handle = ctx.get_vfs_path(f"{namespace}deal.pdf")
    await handle.write_bytes(b"%PDF-stub")

    # Bare form
    async with resolve_input_path("deal.pdf", context=ctx) as r1:
        assert r1.path.read_bytes() == b"%PDF-stub"

    # Already-namespaced form (idempotency)
    async with resolve_input_path(f"{namespace}deal.pdf", context=ctx) as r2:
        assert r2.path.read_bytes() == b"%PDF-stub"


# ── Idempotency under the / -> / normalization that ctx applies ────


@pytest.mark.asyncio
async def test_idempotency_works_with_normalised_namespace_input(
    runtime: KaosRuntime,
) -> None:
    """The ctx normalises ``"/files"`` / ``"files"`` / ``"files/"`` /
    ``"  files  "`` all to canonical ``"files/"``. The idempotency
    check uses that canonical form. Sweep all four variants and
    confirm each one resolves identical content for both bare and
    namespaced inputs."""
    payload = b"sweep-payload"
    for raw in ("/files", "files", "files/", "  files  "):
        ctx = KaosContext(
            session_id=f"s-sweep-{raw.strip()}",
            runtime=runtime,
            vfs=runtime.vfs,
            default_vfs_namespace=raw,
        )
        assert ctx.default_vfs_namespace == "files/"
        handle = ctx.get_vfs_path("files/sweep.txt")
        await handle.write_bytes(payload)

        async with resolve_input_path("sweep.txt", context=ctx) as r1:
            assert r1.path.read_bytes() == payload
        async with resolve_input_path("files/sweep.txt", context=ctx) as r2:
            assert r2.path.read_bytes() == payload
