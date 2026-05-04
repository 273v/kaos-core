"""Cross-session artifact isolation tests.

Pins the security contract that an artifact created by session ``s1``
is invisible to session ``s2`` through every entry point that an
external (MCP) caller can reach: list, inspect, body read, manifest
URI read, and the resource-API fallback in ``KaosContext.read_resource``.

The Python API on ``ArtifactStore`` is intentionally permissive when
called WITHOUT ``caller_session_id`` so trusted in-process callers
(cleanup, persistence reload) keep working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos_core import (
    KaosContext,
    KaosRuntime,
    KaosSettings,
    StorageBackend,
    VFSConfig,
    VirtualFileSystem,
)
from kaos_core.artifacts import ArtifactStore
from kaos_core.exceptions import ResourceError
from kaos_core.tools import ArtifactsInspectTool, ArtifactsListTool


@pytest.fixture
def runtime(tmp_path: Path) -> KaosRuntime:
    settings = KaosSettings()
    rt = KaosRuntime(config=settings)
    rt.vfs = VirtualFileSystem(
        VFSConfig(default_backend=StorageBackend.DISK, disk_base_path=tmp_path / "vfs")
    )
    rt.artifacts = ArtifactStore(
        rt.vfs,
        manifest_context_id=settings.artifact_manifest_context_id,
        manifest_prefix=settings.artifact_manifest_prefix,
    )
    return rt


def _ctx(rt: KaosRuntime, session_id: str) -> KaosContext:
    return KaosContext.create(session_id=session_id, runtime=rt)


async def _create_artifact(rt: KaosRuntime, session_id: str, name: str, body: bytes) -> str:
    """Helper: write a body in `session_id`'s VFS scope and register it."""
    path = f"/{name}"
    await rt.vfs.write(path, body, context_id=session_id)
    manifest = await rt.artifacts.create_from_path(
        path,
        context_id=session_id,
        session_id=session_id,
        name=name,
    )
    return manifest.artifact_id


# ────────────────────────────────────────────────────────────────────
# ArtifactsListTool — only the calling session's artifacts are listed
# ────────────────────────────────────────────────────────────────────


async def test_list_tool_shows_only_caller_session(runtime: KaosRuntime) -> None:
    s1_id = await _create_artifact(runtime, "s1", "s1-secret.txt", b"s1 data")
    s2_id = await _create_artifact(runtime, "s2", "s2-secret.txt", b"s2 data")

    tool = ArtifactsListTool()

    # s1 sees only s1's artifact
    result_s1 = await tool.execute({}, context=_ctx(runtime, "s1"))
    assert not result_s1.isError
    s1_data = result_s1.require_structured()
    s1_artifact_ids = {a["artifact_id"] for a in s1_data["artifacts"]}
    assert s1_artifact_ids == {s1_id}
    assert s2_id not in s1_artifact_ids

    # s2 sees only s2's artifact
    result_s2 = await tool.execute({}, context=_ctx(runtime, "s2"))
    s2_data = result_s2.require_structured()
    s2_artifact_ids = {a["artifact_id"] for a in s2_data["artifacts"]}
    assert s2_artifact_ids == {s2_id}
    assert s1_id not in s2_artifact_ids


async def test_list_tool_ignores_caller_supplied_session_id(runtime: KaosRuntime) -> None:
    """Earlier behavior accepted `session_id` from inputs and used it
    unauthenticated. The MCP tool now ignores any caller-supplied
    `session_id` and always scopes to context.session_id."""
    s1_id = await _create_artifact(runtime, "s1", "s1.txt", b"x")
    await _create_artifact(runtime, "s2", "s2.txt", b"y")

    tool = ArtifactsListTool()
    # Even if a malicious caller tries to pass a different session_id,
    # the tool still scopes to its own context.session_id.
    result = await tool.execute(
        {"session_id": "s1"},  # Attempt to enumerate s1 from s2's session
        context=_ctx(runtime, "s2"),
    )
    data = result.require_structured()
    artifact_ids = {a["artifact_id"] for a in data["artifacts"]}
    assert s1_id not in artifact_ids


# ────────────────────────────────────────────────────────────────────
# ArtifactsInspectTool — manifest reads must respect session ownership
# ────────────────────────────────────────────────────────────────────


async def test_inspect_tool_denies_cross_session_read(runtime: KaosRuntime) -> None:
    s1_id = await _create_artifact(runtime, "s1", "s1.txt", b"x")

    tool = ArtifactsInspectTool()

    # s2 cannot inspect s1's artifact — must get the same uniform
    # "not found" error as a genuinely missing artifact.
    result_cross = await tool.execute({"artifact_id": s1_id}, context=_ctx(runtime, "s2"))
    assert result_cross.isError
    assert "not found" in (result_cross.text or "").lower()

    # And gives the same shape of error for a definitely-missing id.
    result_missing = await tool.execute(
        {"artifact_id": "00000000-0000-0000-0000-000000000000"},
        context=_ctx(runtime, "s2"),
    )
    assert result_missing.isError
    assert "not found" in (result_missing.text or "").lower()


async def test_inspect_tool_allows_same_session(runtime: KaosRuntime) -> None:
    s1_id = await _create_artifact(runtime, "s1", "s1.txt", b"x")

    result = await ArtifactsInspectTool().execute(
        {"artifact_id": s1_id}, context=_ctx(runtime, "s1")
    )
    assert not result.isError
    data = result.require_structured()
    assert data["artifact_id"] == s1_id


# ────────────────────────────────────────────────────────────────────
# ArtifactStore — caller_session_id parameter
# ────────────────────────────────────────────────────────────────────


async def test_store_get_denies_cross_session_caller(runtime: KaosRuntime) -> None:
    s1_id = await _create_artifact(runtime, "s1", "s1.txt", b"x")

    # No caller_session_id → permissive (Python API for trusted callers)
    assert runtime.artifacts.get(s1_id).artifact_id == s1_id

    # caller_session_id="s2" → denied with uniform error
    with pytest.raises(ResourceError, match="Unknown artifact"):
        runtime.artifacts.get(s1_id, caller_session_id="s2")

    # caller_session_id="s1" → allowed
    assert runtime.artifacts.get(s1_id, caller_session_id="s1").artifact_id == s1_id


async def test_store_resolve_denies_cross_session_caller(runtime: KaosRuntime) -> None:
    s1_id = await _create_artifact(runtime, "s1", "s1.txt", b"x")
    uri = f"kaos://artifacts/{s1_id}"

    # By URI: cross-session caller gets uniform error
    with pytest.raises(ResourceError, match="Unknown artifact"):
        runtime.artifacts.resolve(uri, caller_session_id="s2")

    # Same session: works
    assert runtime.artifacts.resolve(uri, caller_session_id="s1").artifact_id == s1_id


async def test_store_read_body_denies_cross_session_caller(runtime: KaosRuntime) -> None:
    s1_id = await _create_artifact(runtime, "s1", "s1.txt", b"s1 secret payload")

    # Cross-session: refuses with uniform error
    with pytest.raises(ResourceError, match="Unknown artifact"):
        await runtime.artifacts.read_body(s1_id, caller_session_id="s2")

    # Same session: returns the bytes
    body = await runtime.artifacts.read_body(s1_id, caller_session_id="s1")
    assert body == b"s1 secret payload"


async def test_store_read_uri_denies_cross_session_caller(runtime: KaosRuntime) -> None:
    s1_id = await _create_artifact(runtime, "s1", "s1.txt", b"s1 secret payload")
    body_uri = f"kaos://artifacts/{s1_id}"

    with pytest.raises(ResourceError, match="Unknown artifact"):
        await runtime.artifacts.read_uri(body_uri, caller_session_id="s2")

    payload = await runtime.artifacts.read_uri(body_uri, caller_session_id="s1")
    assert payload == "s1 secret payload"


# ────────────────────────────────────────────────────────────────────
# KaosContext.read_resource fallback — must propagate session_id
# ────────────────────────────────────────────────────────────────────


async def test_context_read_resource_artifact_fallback_is_session_scoped(
    runtime: KaosRuntime,
) -> None:
    s1_id = await _create_artifact(runtime, "s1", "s1.txt", b"s1 secret payload")
    body_uri = f"kaos://artifacts/{s1_id}"

    # s1 can read its own artifact via the resource API fallback
    payload_same_session = await _ctx(runtime, "s1").read_resource(body_uri)
    assert payload_same_session == "s1 secret payload"

    # s2 must NOT be able to side-channel an s1 artifact through
    # context.read_resource → artifacts.read_uri.
    with pytest.raises(ResourceError, match="Unknown artifact"):
        await _ctx(runtime, "s2").read_resource(body_uri)
