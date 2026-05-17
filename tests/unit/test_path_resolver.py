"""Tests for :mod:`kaos_core.path_resolver`.

The helper is the upstream fix for the production hallucination
incident in the no-hardcoded-caps + VFS audit plan: every file-input
MCP tool across kaos-office / kaos-pdf / kaos-tabular / kaos-source
must route agent-supplied paths through ``resolve_input_path`` so VFS
uploads from a host UI become visible.

The tests cover every documented resolution path:

1. ``kaos://artifacts/<uuid>`` — happy path + cross-session isolation.
2. ``kaos://`` other scheme — VFS read.
3. relative path found in VFS — VFS read.
4. relative path NOT in VFS — clean falls-through error pointing at the
   right alternative tool.
5. absolute filesystem path — no-copy passthrough.
6. mime-type guard — both artifact-store and VFS branches reject the
   wrong mime and tell the agent which tool to try instead.
7. cleanup — temp files are deleted on context exit, original
   filesystem files are NOT.

Live tests against a real disk VFS so we exercise the same
isolation boundary the SPA backend uses in production.
"""

from __future__ import annotations

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
from kaos_core.path_resolver import (
    InputPathResolutionError,
    ResolvedOrigin,
    resolve_input_path,
)
from kaos_core.types.enums import StorageBackend


def _make_runtime(tmp_path: Path) -> KaosRuntime:
    settings = KaosSettings(
        artifact_inline_read_max_bytes=262_144,
        artifact_chunk_size_bytes=64,
    )
    runtime = KaosRuntime(config=settings)
    runtime.vfs = VirtualFileSystem(
        VFSConfig(default_backend=StorageBackend.DISK, disk_base_path=tmp_path / "vfs")
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


def _context(runtime: KaosRuntime, *, session_id: str = "s-test") -> KaosContext:
    return KaosContext(session_id=session_id, runtime=runtime, vfs=runtime.vfs)


# ---------------------------------------------------------------------------
# 1. Artifact URI resolution
# ---------------------------------------------------------------------------


async def test_artifact_uri_yields_temp_path_with_metadata(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    ctx = _context(runtime, session_id="s-art")
    body = b"hello from the artifact store"
    manifest = await runtime.artifacts.create_from_bytes(
        body,
        context_id=ctx.session_id,
        session_id=ctx.session_id,
        name="hello.txt",
        mime_type="text/plain",
        source_uri="https://example.test/hello.txt",
    )

    uri = f"kaos://artifacts/{manifest.artifact_id}"
    async with resolve_input_path(uri, context=ctx) as resolved:
        assert resolved.origin is ResolvedOrigin.ARTIFACT
        assert resolved.artifact_id == manifest.artifact_id
        assert resolved.path.exists()
        assert resolved.path.read_bytes() == body
        assert resolved.mime_type == "text/plain"
        assert resolved.size == len(body)
        # body_uri populated so tools can echo it into structuredContent.
        assert resolved.body_uri and manifest.artifact_id in resolved.body_uri
        # source_uri (Stage A) round-trips so the SPA's ArtifactCard
        # can render the originating URL.
        assert resolved.source_uri == "https://example.test/hello.txt"
        temp_path = resolved.path

    # Cleanup ran — temp file is gone.
    assert not temp_path.exists()


async def test_artifact_uri_cross_session_isolation_refuses(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    owner_ctx = _context(runtime, session_id="s-owner")
    body = b"private bytes"
    manifest = await runtime.artifacts.create_from_bytes(
        body,
        context_id=owner_ctx.session_id,
        session_id=owner_ctx.session_id,
        name="private.txt",
        mime_type="text/plain",
    )

    intruder_ctx = _context(runtime, session_id="s-intruder")
    uri = f"kaos://artifacts/{manifest.artifact_id}"
    with pytest.raises(InputPathResolutionError) as exc_info:
        async with resolve_input_path(uri, context=intruder_ctx):
            pass  # pragma: no cover - we expect raise before yield
    msg = str(exc_info.value)
    assert "not found" in msg.lower() or "not readable" in msg.lower()
    # Error message gives the agent a path forward, not just "denied".
    assert "kaos-core-list-artifacts" in msg


async def test_artifact_uri_malformed_yields_clean_error(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    ctx = _context(runtime)
    with pytest.raises(InputPathResolutionError) as exc_info:
        async with resolve_input_path("kaos://artifacts/", context=ctx):
            pass  # pragma: no cover
    msg = str(exc_info.value)
    assert "kaos://artifacts/<id>" in msg


async def test_artifact_uri_mime_mismatch_explains_alternative(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    ctx = _context(runtime)
    html = b"<!doctype html><html><body>not json</body></html>"
    manifest = await runtime.artifacts.create_from_bytes(
        html,
        context_id=ctx.session_id,
        session_id=ctx.session_id,
        name="page.html",
        mime_type="text/html",
    )
    uri = f"kaos://artifacts/{manifest.artifact_id}"
    with pytest.raises(InputPathResolutionError) as exc_info:
        async with resolve_input_path(
            uri,
            context=ctx,
            allowed_mime_types=("application/json",),
        ):
            pass  # pragma: no cover
    msg = str(exc_info.value)
    assert "text/html" in msg
    assert "application/json" in msg
    # Error nudges agent toward the right tool, not the same one again.
    assert "kaos-content-parse-html" in msg or "matching kaos-office" in msg


async def test_artifact_uri_size_cap_blocks_oversized(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    ctx = _context(runtime)
    body = b"x" * 1024
    manifest = await runtime.artifacts.create_from_bytes(
        body,
        context_id=ctx.session_id,
        session_id=ctx.session_id,
        name="big.bin",
        mime_type="application/octet-stream",
    )
    uri = f"kaos://artifacts/{manifest.artifact_id}"
    with pytest.raises(InputPathResolutionError) as exc_info:
        async with resolve_input_path(uri, context=ctx, max_bytes=512):
            pass  # pragma: no cover
    msg = str(exc_info.value)
    assert "1024" in msg
    assert "kaos-core-artifact-read" in msg


# ---------------------------------------------------------------------------
# 2. kaos:// non-artifact scheme → VFS read
# ---------------------------------------------------------------------------


async def test_kaos_uri_non_artifact_scheme_reads_vfs(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    ctx = _context(runtime, session_id="s-vfs-uri")
    handle = ctx.get_vfs_path("workspace/notes.txt")
    await handle.write_bytes(b"vfs-uri payload")

    async with resolve_input_path(
        "kaos://workspace/notes.txt",
        context=ctx,
    ) as resolved:
        assert resolved.origin is ResolvedOrigin.VFS
        assert resolved.path.read_bytes() == b"vfs-uri payload"
        assert resolved.mime_type == "text/plain"


# ---------------------------------------------------------------------------
# 3. Relative path → VFS first
# ---------------------------------------------------------------------------


async def test_relative_path_resolves_via_vfs(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    ctx = _context(runtime, session_id="s-spa-upload")
    # This mirrors the production SPA upload layout exactly:
    # backend/.kaos-vfs/sessions/<sid>/files/EMNA Mutual NDA.docx
    vfs_path = "files/EMNA Mutual NDA.docx"
    handle = ctx.get_vfs_path(vfs_path)
    await handle.write_bytes(b"PK\x03\x04 (fake docx zip header)")

    async with resolve_input_path(vfs_path, context=ctx) as resolved:
        assert resolved.origin is ResolvedOrigin.VFS
        assert resolved.path.exists()
        assert resolved.path.read_bytes().startswith(b"PK")
        assert (
            resolved.mime_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        # Temp file preserves the .docx extension so python-docx /
        # openpyxl readers see the format they expect.
        assert resolved.path.suffix == ".docx"


async def test_relative_path_not_in_vfs_falls_through_to_clear_error(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    ctx = _context(runtime, session_id="s-missing")
    with pytest.raises(InputPathResolutionError) as exc_info:
        async with resolve_input_path("nope/missing.docx", context=ctx):
            pass  # pragma: no cover
    msg = str(exc_info.value)
    assert "session VFS" in msg or "local filesystem" in msg
    # Agent must be told which tool would list what's available, not
    # left guessing at the path.
    assert "kaos-core-vfs-list" in msg


# ---------------------------------------------------------------------------
# 4. Absolute filesystem path — no copy
# ---------------------------------------------------------------------------


async def test_absolute_path_is_passthrough_no_temp_copy(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    ctx = _context(runtime)
    real = tmp_path / "real.txt"
    real.write_bytes(b"on-disk bytes")

    async with resolve_input_path(str(real), context=ctx) as resolved:
        assert resolved.origin is ResolvedOrigin.FILESYSTEM
        assert resolved.path == real
        assert resolved.path.exists()

    # Filesystem files are NEVER cleaned up by the resolver.
    assert real.exists()
    assert real.read_bytes() == b"on-disk bytes"


async def test_absolute_path_missing_yields_clean_error(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    ctx = _context(runtime)
    with pytest.raises(InputPathResolutionError) as exc_info:
        async with resolve_input_path("/this/does/not/exist.docx", context=ctx):
            pass  # pragma: no cover
    msg = str(exc_info.value)
    assert "not found" in msg.lower()
    assert "kaos-core-vfs-list" in msg or "absolute" in msg


# ---------------------------------------------------------------------------
# 5. Mime-type guard on filesystem path
# ---------------------------------------------------------------------------


async def test_filesystem_mime_mismatch_blocks_before_open(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    ctx = _context(runtime)
    real = tmp_path / "page.html"
    real.write_bytes(b"<!doctype html>")
    with pytest.raises(InputPathResolutionError) as exc_info:
        async with resolve_input_path(
            str(real),
            context=ctx,
            allowed_mime_types=("application/pdf",),
        ):
            pass  # pragma: no cover
    msg = str(exc_info.value)
    assert "text/html" in msg
    assert "application/pdf" in msg


# ---------------------------------------------------------------------------
# 6. Empty / nonsense input
# ---------------------------------------------------------------------------


async def test_empty_input_raises_with_hint(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    ctx = _context(runtime)
    with pytest.raises(InputPathResolutionError) as exc_info:
        async with resolve_input_path("", context=ctx):
            pass  # pragma: no cover
    msg = str(exc_info.value)
    assert "empty" in msg.lower()


async def test_whitespace_only_input_raises(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    ctx = _context(runtime)
    with pytest.raises(InputPathResolutionError):
        async with resolve_input_path("   \t\n  ", context=ctx):
            pass  # pragma: no cover


# ---------------------------------------------------------------------------
# 7. No runtime / no VFS — informative errors instead of pythonic chaos
# ---------------------------------------------------------------------------


async def test_no_artifacts_store_raises_clean_error(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    ctx = _context(runtime)
    ctx.runtime = None
    with pytest.raises(InputPathResolutionError) as exc_info:
        async with resolve_input_path(
            "kaos://artifacts/some-id-1234",
            context=ctx,
        ):
            pass  # pragma: no cover
    assert "ArtifactStore" in str(exc_info.value) or "artifact store" in str(exc_info.value)
