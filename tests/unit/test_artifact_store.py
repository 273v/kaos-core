"""Comprehensive tests for ArtifactStore paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos_core import (
    ArtifactManifest,
    ArtifactRole,
    ArtifactStore,
    KaosContext,
    KaosRuntime,
    KaosSettings,
    ResourceError,
    VFSConfig,
    VirtualFileSystem,
)
from kaos_core.types.enums import StorageBackend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


async def _write_and_create(
    runtime: KaosRuntime,
    *,
    filename: str,
    content: str | bytes = "hello",
    session_id: str = "s1",
    workflow_id: str | None = None,
    role: ArtifactRole = ArtifactRole.BODY,
    name: str | None = None,
    mime_type: str = "text/plain",
) -> ArtifactManifest:
    context = KaosContext.create(session_id=session_id, runtime=runtime)
    vfs_path = context.get_vfs_path(f"artifacts/{filename}")
    if isinstance(content, str):
        await vfs_path.write_text(content)
    else:
        await vfs_path.write_bytes(content)
    return await runtime.artifacts.create_from_path(
        f"artifacts/{filename}",
        context_id=session_id,
        session_id=session_id,
        workflow_id=workflow_id,
        name=name or filename,
        role=role,
        mime_type=mime_type,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_list_artifacts_no_filter(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m1 = await _write_and_create(runtime, filename="a.txt", content="aaa")
    m2 = await _write_and_create(runtime, filename="b.txt", content="bbb")
    m3 = await _write_and_create(runtime, filename="c.txt", content="ccc")

    result = runtime.artifacts.list_artifacts()
    ids = {m.artifact_id for m in result}
    assert len(result) == 3
    assert {m1.artifact_id, m2.artifact_id, m3.artifact_id} == ids


async def test_list_artifacts_filter_by_session(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m1 = await _write_and_create(runtime, filename="a.txt", session_id="alpha")
    await _write_and_create(runtime, filename="b.txt", session_id="beta")

    result = runtime.artifacts.list_artifacts(session_id="alpha")
    assert len(result) == 1
    assert result[0].artifact_id == m1.artifact_id


async def test_list_artifacts_filter_by_workflow(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m1 = await _write_and_create(runtime, filename="a.txt", workflow_id="wf-1")
    await _write_and_create(runtime, filename="b.txt", workflow_id="wf-2")
    await _write_and_create(runtime, filename="c.txt")  # no workflow

    result = runtime.artifacts.list_artifacts(workflow_id="wf-1")
    assert len(result) == 1
    assert result[0].artifact_id == m1.artifact_id


async def test_list_artifacts_filter_by_role(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m1 = await _write_and_create(runtime, filename="a.txt", role=ArtifactRole.SUMMARY)
    await _write_and_create(runtime, filename="b.txt", role=ArtifactRole.BODY)

    result = runtime.artifacts.list_artifacts(role=ArtifactRole.SUMMARY)
    assert len(result) == 1
    assert result[0].artifact_id == m1.artifact_id


async def test_resolve_by_uri(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="r.txt")

    resolved = runtime.artifacts.resolve(m.uri)
    assert resolved.artifact_id == m.artifact_id


async def test_resolve_by_body_uri(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="r.txt")

    resolved = runtime.artifacts.resolve(m.body_uri)
    assert resolved.artifact_id == m.artifact_id


async def test_resolve_by_manifest_uri(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="r.txt")

    resolved = runtime.artifacts.resolve(m.manifest_uri)
    assert resolved.artifact_id == m.artifact_id


async def test_resolve_unknown_raises(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)

    with pytest.raises(ResourceError, match="Unknown artifact"):
        runtime.artifacts.resolve("kaos://artifacts/nonexistent-id/body")


async def test_read_uri_manifest(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="doc.txt", content="manifest-test")

    result = await runtime.artifacts.read_uri(m.manifest_uri)
    assert isinstance(result, str)
    assert '"artifact_id"' in result
    assert m.artifact_id in result


async def test_read_uri_body(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="doc.txt", content="body-content")

    result = await runtime.artifacts.read_uri(m.body_uri)
    assert result == "body-content"


async def test_read_text(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="text.txt", content="decoded string")

    result = await runtime.artifacts.read_text(m.artifact_id)
    assert isinstance(result, str)
    assert result == "decoded string"


async def test_read_chunk_negative_index_raises(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="chunk.txt", content="0123456789")

    with pytest.raises(ResourceError, match="chunk index must be non-negative"):
        await runtime.artifacts.read_chunk(m.artifact_id, chunk_index=-1)


async def test_read_chunk_out_of_range_raises(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="chunk.txt", content="short")

    with pytest.raises(ResourceError, match="chunk is out of range"):
        await runtime.artifacts.read_chunk(m.artifact_id, chunk_index=9999, chunk_size=64)


async def test_register_direct(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)

    # Write backing file so resolve/read would work if needed
    context = KaosContext.create(session_id="direct", runtime=runtime)
    vfs_path = context.get_vfs_path("artifacts/direct.txt")
    await vfs_path.write_text("direct-content")

    manifest = ArtifactManifest(
        artifact_id="custom-id-001",
        session_id="direct",
        context_id="direct",
        name="direct-artifact",
        uri="kaos://artifacts/custom-id-001",
        role=ArtifactRole.BODY,
        mime_type="text/plain",
        size=14,
        path="artifacts/direct.txt",
    )
    returned = runtime.artifacts.register(manifest)
    assert returned.artifact_id == "custom-id-001"

    resolved = runtime.artifacts.resolve("custom-id-001")
    assert resolved.name == "direct-artifact"

    resolved_by_uri = runtime.artifacts.resolve(manifest.body_uri)
    assert resolved_by_uri.artifact_id == "custom-id-001"


async def test_list_retained_paths(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m1 = await _write_and_create(runtime, filename="keep1.txt", session_id="ctx-a")
    m2 = await _write_and_create(runtime, filename="keep2.txt", session_id="ctx-a")
    await _write_and_create(runtime, filename="other.txt", session_id="ctx-b")

    paths = runtime.artifacts.list_retained_paths(context_id="ctx-a")
    assert paths == {m1.path, m2.path}


async def test_read_body_negative_start_raises(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="neg.txt", content="negative")

    with pytest.raises(ResourceError, match="start must be non-negative"):
        await runtime.artifacts.read_body(m.artifact_id, start=-1)


async def test_read_body_zero_length_raises(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="zero.txt", content="zero-length")

    with pytest.raises(ResourceError, match="length must be positive"):
        await runtime.artifacts.read_body(m.artifact_id, length=0)


# ---------------------------------------------------------------------------
# ArtifactManifest helpers: to_resource_link, to_tool_result
# ---------------------------------------------------------------------------


async def test_to_resource_link(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(
        runtime, filename="link.txt", content="hello", mime_type="text/plain"
    )

    link = m.to_resource_link()
    assert link.name == m.name
    assert link.uri == m.body_uri
    assert link.mimeType == "text/plain"
    assert link.size == m.size


async def test_to_resource_link_with_overrides(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="link2.txt", content="hello")

    link = m.to_resource_link(title="My Title", description="My Desc")
    assert link.title == "My Title"
    assert link.description == "My Desc"


async def test_to_tool_result_tiny_artifact_inlines(tmp_path: Path) -> None:
    """Artifacts smaller than INLINE_THRESHOLD get inlined when body is provided."""
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="tiny.txt", content="small")

    result = m.to_tool_result(inline_body="small")
    assert not result.isError
    # Tiny artifact with inline body → text only, no link
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert result.text == "small"


async def test_to_tool_result_tiny_no_body_gets_link(tmp_path: Path) -> None:
    """Tiny artifact without inline_body still gets a resource link."""
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="tiny2.txt", content="small")

    result = m.to_tool_result(summary="A small file")
    assert len(result.content) == 2
    assert result.content[0].type == "text"
    assert result.content[1].type == "resource_link"


async def test_to_tool_result_medium_artifact(tmp_path: Path) -> None:
    """Medium artifacts (>16KB, <256KB) get summary + resource link."""
    from kaos_core.artifacts.models import INLINE_THRESHOLD

    runtime = _make_runtime(tmp_path)
    content = "x" * (INLINE_THRESHOLD + 100)
    m = await _write_and_create(runtime, filename="medium.txt", content=content)

    result = m.to_tool_result(summary="A medium document", inline_body=content)
    # inline_body is ignored for medium artifacts (size >= INLINE_THRESHOLD)
    assert len(result.content) == 2
    assert result.content[0].type == "text"
    assert result.text == "A medium document"
    assert result.content[1].type == "resource_link"


async def test_to_tool_result_large_artifact_link_only(tmp_path: Path) -> None:
    """Large artifacts (>256KB) get link only (no summary unless provided)."""
    from kaos_core.artifacts.models import SUMMARY_THRESHOLD

    runtime = _make_runtime(tmp_path)
    content = "x" * (SUMMARY_THRESHOLD + 100)
    m = await _write_and_create(runtime, filename="large.txt", content=content)

    result = m.to_tool_result()
    assert len(result.content) == 1
    assert result.content[0].type == "resource_link"


async def test_to_tool_result_structured_content(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    m = await _write_and_create(runtime, filename="struct.txt", content="data")

    result = m.to_tool_result(
        summary="Parsed document",
        structured_content={"pages": 42, "title": "My Doc"},
    )
    assert result.structuredContent == {"pages": 42, "title": "My Doc"}


def test_threshold_constants() -> None:
    from kaos_core.artifacts.models import INLINE_THRESHOLD, SUMMARY_THRESHOLD

    assert INLINE_THRESHOLD == 16_384
    assert SUMMARY_THRESHOLD == 262_144
    assert INLINE_THRESHOLD < SUMMARY_THRESHOLD
