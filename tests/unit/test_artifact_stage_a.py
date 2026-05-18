"""Stage A foundation tests for the artifact subsystem.

These exercise the artifact-first primitives required by the broader
``no-hardcoded-caps-and-artifact-first-tool-results`` plan that lives in
the kaos-modules monorepo:

1. :meth:`ArtifactStore.create_from_bytes` materialises raw bytes into
   the VFS and produces an artifact manifest equivalent to
   ``create_from_path``.
2. ``ArtifactManifest.source_uri`` is a first-class field round-tripping
   through persistence.
3. :class:`KaosCoreArtifactSettings` drives ``to_tool_result`` tiering
   and the module-level ``INLINE_THRESHOLD`` / ``SUMMARY_THRESHOLD``
   constants stay in sync with the settings defaults.
4. ``ArtifactStore.get`` enforces session-scoped access via
   ``caller_session_id`` (already present, re-asserted here so
   regressions in this load-bearing security boundary surface
   immediately).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos_core import (
    ArtifactManifest,
    ArtifactStore,
    KaosCoreArtifactSettings,
    KaosRuntime,
    KaosSettings,
    ResourceError,
    VFSConfig,
    VirtualFileSystem,
)
from kaos_core.artifacts.models import (
    INLINE_THRESHOLD,
    SUMMARY_THRESHOLD,
)
from kaos_core.types.enums import ArtifactRole, StorageBackend


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


# ---------------------------------------------------------------------------
# 1. create_from_bytes
# ---------------------------------------------------------------------------


async def test_create_from_bytes_materialises_into_vfs(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    payload = b"abc123" * 100  # 600 bytes — well under any inline threshold
    manifest = await runtime.artifacts.create_from_bytes(
        payload,
        context_id="s-bytes",
        session_id="s-bytes",
        name="hello.txt",
        mime_type="text/plain",
        source_uri="https://example.test/source/hello.txt",
    )

    assert isinstance(manifest, ArtifactManifest)
    assert manifest.size == len(payload)
    assert manifest.mime_type == "text/plain"
    assert manifest.source_uri == "https://example.test/source/hello.txt"
    assert manifest.path.startswith("artifacts/")

    body = await runtime.artifacts.read_body(manifest.artifact_id)
    assert body == payload


async def test_create_from_bytes_uri_indices_resolve(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    manifest = await runtime.artifacts.create_from_bytes(
        b"resolve-me",
        context_id="ctx",
        session_id="ctx",
        name="probe.bin",
        mime_type="application/octet-stream",
    )

    assert runtime.artifacts.resolve(manifest.uri).artifact_id == manifest.artifact_id
    assert runtime.artifacts.resolve(manifest.body_uri).artifact_id == manifest.artifact_id
    assert runtime.artifacts.resolve(manifest.manifest_uri).artifact_id == manifest.artifact_id


async def test_create_from_bytes_rejects_non_bytes(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    with pytest.raises(TypeError):
        await runtime.artifacts.create_from_bytes(
            "not bytes",  # ty: ignore[invalid-argument-type]
            context_id="ctx",
            session_id="ctx",
            name="oops.txt",
        )


async def test_create_from_bytes_sanitises_name_in_path(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    manifest = await runtime.artifacts.create_from_bytes(
        b"x",
        context_id="ctx",
        session_id="ctx",
        name="../etc/passwd",
    )
    # The path must NOT escape the artifacts subdir — slashes are sanitised.
    assert "/etc/" not in manifest.path
    assert manifest.path.startswith("artifacts/")


async def test_create_from_bytes_checksum_optional(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    payload = b"checksum-me"
    without = await runtime.artifacts.create_from_bytes(
        payload,
        context_id="ctx",
        session_id="ctx",
        name="a.bin",
    )
    with_sum = await runtime.artifacts.create_from_bytes(
        payload,
        context_id="ctx",
        session_id="ctx",
        name="b.bin",
        checksum=True,
    )
    assert without.checksum is None
    assert with_sum.checksum is not None
    assert len(with_sum.checksum) == 64  # sha256 hex


# ---------------------------------------------------------------------------
# 2. source_uri first-class field
# ---------------------------------------------------------------------------


async def test_source_uri_persists_and_reloads(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    manifest = await runtime.artifacts.create_from_bytes(
        b"persist",
        context_id="ctx",
        session_id="ctx",
        name="doc.txt",
        source_uri="https://www.federalregister.gov/d/2025-12345",
        role=ArtifactRole.BODY,
    )
    assert manifest.source_uri == "https://www.federalregister.gov/d/2025-12345"

    runtime.artifacts._artifacts.clear()
    runtime.artifacts._uri_index.clear()
    restored = await runtime.artifacts._restore_manifest(manifest.artifact_id)
    assert restored is not None
    assert restored.source_uri == "https://www.federalregister.gov/d/2025-12345"


def test_source_uri_defaults_to_none() -> None:
    manifest = ArtifactManifest(
        artifact_id="x",
        session_id="s",
        context_id="s",
        name="n",
        uri="kaos://artifacts/x",
        role=ArtifactRole.BODY,
        path="p",
    )
    assert manifest.source_uri is None


# ---------------------------------------------------------------------------
# 3. Settings-driven thresholds
# ---------------------------------------------------------------------------


def test_default_settings_match_module_constants() -> None:
    defaults = KaosCoreArtifactSettings()
    assert defaults.inline_threshold == INLINE_THRESHOLD
    assert defaults.summary_threshold == SUMMARY_THRESHOLD


def test_to_tool_result_uses_settings_for_inline_tier() -> None:
    tiny = ArtifactManifest(
        artifact_id="tiny",
        session_id="s",
        context_id="s",
        name="t.txt",
        uri="kaos://artifacts/tiny",
        role=ArtifactRole.BODY,
        mime_type="text/plain",
        size=10,
        path="p",
    )
    result = tiny.to_tool_result(summary="summary text", inline_body="full body")
    assert result.text == "full body"


def test_to_tool_result_settings_override_promotes_to_summary_tier() -> None:
    tiny = ArtifactManifest(
        artifact_id="tiny",
        session_id="s",
        context_id="s",
        name="t.txt",
        uri="kaos://artifacts/tiny",
        role=ArtifactRole.BODY,
        mime_type="text/plain",
        size=10,
        path="p",
    )
    strict = KaosCoreArtifactSettings(inline_threshold=1, summary_threshold=100)
    result = tiny.to_tool_result(
        summary="just the summary",
        inline_body="full body",
        settings=strict,
    )
    assert result.text == "just the summary"
    assert any(getattr(item, "uri", None) == tiny.body_uri for item in result.content)


def test_to_tool_result_omits_summary_at_summary_threshold() -> None:
    manifest = ArtifactManifest(
        artifact_id="large",
        session_id="s",
        context_id="s",
        name="large.txt",
        uri="kaos://artifacts/large",
        role=ArtifactRole.BODY,
        mime_type="text/plain",
        size=100,
        path="p",
    )
    settings = KaosCoreArtifactSettings(inline_threshold=10, summary_threshold=100)

    result = manifest.to_tool_result(
        summary="summary should be omitted",
        inline_body="full body should be omitted",
        settings=settings,
    )

    assert len(result.content) == 1
    assert result.content[0].type == "resource_link"
    assert result.text is None


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAOS_CORE_ARTIFACT_INLINE_THRESHOLD", "32768")
    monkeypatch.setenv("KAOS_CORE_ARTIFACT_SUMMARY_THRESHOLD", "524288")
    settings = KaosCoreArtifactSettings()
    assert settings.inline_threshold == 32_768
    assert settings.summary_threshold == 524_288


# ---------------------------------------------------------------------------
# 4. Session-scoped access enforcement (regression net)
# ---------------------------------------------------------------------------


async def test_get_rejects_cross_session_caller(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    manifest = await runtime.artifacts.create_from_bytes(
        b"private",
        context_id="alpha",
        session_id="alpha",
        name="secret.bin",
    )
    assert (
        runtime.artifacts.get(manifest.artifact_id, caller_session_id="alpha").artifact_id
        == manifest.artifact_id
    )
    with pytest.raises(ResourceError, match="Unknown artifact"):
        runtime.artifacts.get(manifest.artifact_id, caller_session_id="beta")


async def test_resolve_rejects_cross_session_caller(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    manifest = await runtime.artifacts.create_from_bytes(
        b"private",
        context_id="alpha",
        session_id="alpha",
        name="secret.bin",
    )
    with pytest.raises(ResourceError, match="Unknown artifact"):
        runtime.artifacts.resolve(manifest.body_uri, caller_session_id="beta")
