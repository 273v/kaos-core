from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from kaos_core import (
    ArtifactRole,
    KaosContext,
    KaosResource,
    KaosRuntime,
    ResourceMetadata,
    ResourceType,
    ToolCapability,
    ToolCategory,
    VFSConfig,
    VFSFile,
    VFSWalkOptions,
    VirtualFileSystem,
    kaos_tool,
)
from kaos_core.protocol.capabilities import ClientCapabilities, RootsCapability, ServerCapabilities
from kaos_core.protocol.initialize import Implementation, InitializeRequest, InitializeResult
from kaos_core.protocol.roots import Root
from kaos_core.registry import container as runtime_container
from kaos_core.types.enums import IsolationMode, StorageBackend
from kaos_core.vfs.backends import DiskBackend, S3Backend


class ResourceProbe(KaosResource):
    def __init__(self, value: str = "payload") -> None:
        super().__init__()
        self.value = value

    @property
    def metadata(self) -> ResourceMetadata:
        return ResourceMetadata(
            uri="kaos://kaos-core/docs/probe",
            name="probe",
            description="Probe resource",
            resource_type=ResourceType.DOCUMENT,
            provider_module="kaos-core",
            version="0.1.0",
        )

    async def read(self, context: KaosContext | None = None) -> str:
        del context
        return self.value

    async def get_metadata(self, context: KaosContext | None = None) -> dict[str, Any]:
        del context
        return {"value": self.value}


@kaos_tool(
    name="kaos-core-runtime-ping",
    description="Return a ping result",
    category=ToolCategory.UTILITY,
    capability=ToolCapability.TRANSFORM,
    module_name="kaos-core",
    version="0.1.0",
    auto_register=False,
)
async def ping() -> str:
    return "pong"


async def test_context_runtime_resource_and_progress_behaviors(runtime: KaosRuntime) -> None:
    resource = ResourceProbe("resource-value")
    runtime.resources.register_resource(resource)

    init_request = InitializeRequest(
        protocol_version="2025-11-25",
        capabilities=ClientCapabilities(
            sampling={},
            elicitation={},
            roots=RootsCapability(listChanged=True),
        ),
        client_info=Implementation(name="client", version="1.0.0"),
    )
    init_result = InitializeResult(
        protocol_version="2025-11-25",
        capabilities=ServerCapabilities(tools={}, logging={}),
        server_info=Implementation(name="server", version="1.0.0"),
    )
    roots = [Root(uri="file:///workspace", name="workspace")]

    context = KaosContext.create_from_initialize(
        init_result,
        session_id="session-1",
        runtime=runtime,
        init_request=init_request,
        roots=roots,
    )
    context.info("info message", step="setup")
    context.warning("warning message", step="warn")
    context.error("error message", step="error")

    sync_progress: list[tuple[float, float | None, str | None]] = []
    async_progress: list[tuple[float, float | None, str | None]] = []

    context.set_progress_callback(
        lambda current, total, message: sync_progress.append((current, total, message))
    )
    await context.report_progress(1.0, 2.0, "half")

    async def async_callback(current: float, total: float | None, message: str | None) -> None:
        async_progress.append((current, total, message))

    context.set_progress_callback(async_callback)
    await context.report_progress(2.0, 2.0, "done")

    assert context.supports_sampling() is True
    assert context.supports_elicitation() is True
    assert context.supports_roots() is True
    assert context.get_config("log_level") == runtime.settings.log_level
    assert context.get_config("missing", "fallback") == "fallback"
    context.set_config("feature", True)
    assert context.get_config("feature") is True
    assert await context.read_resource("kaos://kaos-core/docs/probe") == "resource-value"
    assert sync_progress == [(1.0, 2.0, "half")]
    assert async_progress == [(2.0, 2.0, "done")]

    child = context.create_child_context(metadata={"role": "child"}, config={"feature": False})
    assert child.session_id == "session-1"
    assert child.trace_id is None
    assert child.metadata["role"] == "child"
    assert child.client_capabilities == context.client_capabilities
    assert child.server_capabilities == context.server_capabilities
    assert child.protocol_version == context.protocol_version
    assert child.roots == roots
    assert child.get_config("feature") is False

    path = context.get_vfs_path("notes.txt")
    await path.write_text("hello")
    assert await path.read_text() == "hello"
    await context.cleanup()
    assert await path.exists() is False

    detached = KaosContext.create(session_id="detached")
    with pytest.raises(RuntimeError):
        await detached.read_resource("kaos://kaos-core/docs/probe")

    reconstructed = KaosContext.create_from_dict(
        {"session_id": "dict-session", "metadata": {"source": "dict"}}
    )
    assert reconstructed.session_id == "dict-session"
    assert reconstructed.metadata == {"source": "dict"}
    assert reconstructed.vfs is not None


async def test_runtime_defaults_resource_helpers_and_shutdown() -> None:
    runtime_container._default_runtime.set(None)
    created = KaosRuntime.default()
    assert isinstance(created, KaosRuntime)

    alternate = KaosRuntime()
    KaosRuntime.set_default(alternate)
    assert KaosRuntime.default() is alternate

    alternate.tools.register_tool(ping)
    await ping.startup()
    assert ping.is_initialized is True
    await alternate.shutdown()
    assert ping.is_initialized is False

    resource = ResourceProbe()
    assert [item async for item in resource.stream_read()] == ["payload"]

    events: list[dict[str, Any]] = []

    async def async_subscriber(event: dict[str, Any]) -> None:
        await asyncio.sleep(0)
        events.append({"async": event["kind"]})

    def sync_subscriber(event: dict[str, Any]) -> None:
        events.append({"sync": event["kind"]})

    async_id = await resource.subscribe_changes(async_subscriber)
    sync_id = await resource.subscribe_changes(sync_subscriber)
    await resource._notify_subscribers({"kind": "updated"})
    await resource.unsubscribe_changes(async_id)
    await resource.unsubscribe_changes(sync_id)

    assert events == [{"async": "updated"}, {"sync": "updated"}]
    assert resource._repr_json_()["uri"] == "kaos://kaos-core/docs/probe"
    assert "Probe resource" in resource._repr_markdown_()
    assert str(resource) == "kaos://kaos-core/docs/probe"
    assert "ResourceProbe" in repr(resource)
    assert "stream_read" in dir(resource)


async def test_vfs_backends_paths_and_file_operations(tmp_path: Path) -> None:
    memory_vfs = VirtualFileSystem()
    assert memory_vfs.config.default_backend is StorageBackend.DISK
    path = memory_vfs.get_path("folder/file.txt", context_id="ctx")

    assert path.name == "file.txt"
    assert path.parts == ("folder", "file.txt")
    assert path.parent / "file.txt"

    await path.parent.mkdir()
    await path.write_bytes(b"abc")
    assert await path.exists() is True
    assert await path.is_file() is True
    assert await path.parent.is_dir() is True
    assert await path.read_bytes() == b"abc"
    children = await path.parent.iterdir()
    assert len(children) == 1
    await path.parent.rmdir()
    assert await path.exists() is False

    scoped = await memory_vfs.list("", context_id="ctx")
    assert scoped == []

    namespace_vfs = VirtualFileSystem(
        VFSConfig(default_backend=StorageBackend.MEMORY, isolation_mode=IsolationMode.NAMESPACE)
    )
    await namespace_vfs.write("shared.txt", b"team", context_id="team:one")
    assert await namespace_vfs.read("shared.txt", context_id="team:two") == b"team"
    assert namespace_vfs._scope("shared.txt", "team:one") == "team/shared.txt"
    assert namespace_vfs._scope_prefix("team:two") == "team/"
    assert namespace_vfs._strip_scope("team/shared.txt", "team:two") == "shared.txt"

    global_vfs = VirtualFileSystem(
        VFSConfig(default_backend=StorageBackend.MEMORY, isolation_mode=IsolationMode.GLOBAL)
    )
    await global_vfs.write("global.txt", b"visible", context_id="ignored")
    assert await global_vfs.read("global.txt", context_id="other") == b"visible"
    assert global_vfs._scope("global.txt", "ignored") == "global.txt"
    await global_vfs.delete("global.txt", context_id="other")
    assert await global_vfs.exists("global.txt", context_id="ignored") is False

    disk_backend = DiskBackend(tmp_path / "disk")
    await disk_backend.write("logs/output.txt", b"log")
    assert await disk_backend.exists("logs/output.txt") is True
    assert await disk_backend.list("logs") == ["logs/output.txt"]
    await disk_backend.delete("logs/output.txt")
    assert await disk_backend.exists("logs/output.txt") is False
    assert await disk_backend.list("logs") == []

    s3_backend = S3Backend()
    with pytest.raises(NotImplementedError):
        await s3_backend.read("bucket/key")
    with pytest.raises(NotImplementedError):
        await s3_backend.write("bucket/key", b"data")
    with pytest.raises(NotImplementedError):
        await s3_backend.delete("bucket/key")
    with pytest.raises(NotImplementedError):
        await s3_backend.exists("bucket/key")
    with pytest.raises(NotImplementedError):
        await s3_backend.list("bucket")

    raw = VFSFile()
    assert raw.write(b"abcdef") == 6
    assert raw.tell() == 6
    assert raw.seek(2) == 2
    assert raw.read(2) == b"cd"
    raw.close()
    assert raw.closed is True


async def test_vfs_stat_ranges_pages_and_artifacts(tmp_path: Path) -> None:
    runtime = KaosRuntime()
    runtime.vfs = VirtualFileSystem(
        VFSConfig(default_backend=StorageBackend.DISK, disk_base_path=tmp_path / "vfs")
    )
    runtime.artifacts = runtime.artifacts.__class__(runtime.vfs)

    context = KaosContext.create(session_id="artifact-session", runtime=runtime)
    report = context.get_vfs_path("artifacts/report.txt")
    await report.write_text("abcdefghijklmnopqrstuvwxyz")

    stat = await report.stat()
    assert stat.exists is True
    assert stat.kind == "file"
    assert stat.size == 26
    assert stat.mime_type == "text/plain"

    assert await report.read_range(5, 4) == b"fghi"

    page = await runtime.vfs.list_page("artifacts", context_id=context.session_id, limit=1)
    assert page.items == ["artifacts/report.txt"]
    assert page.next_cursor is None

    walked = await runtime.vfs.walk(
        "artifacts",
        context_id=context.session_id,
        options=VFSWalkOptions(patterns=["artifacts/*.txt"]),
    )
    assert walked.total_count == 1
    assert walked.items[0].path == "artifacts/report.txt"

    assert (
        runtime.vfs.safe_join("artifacts", "nested", "summary.md") == "artifacts/nested/summary.md"
    )
    with pytest.raises(ValueError):
        runtime.vfs.safe_join("artifacts", "../escape.txt")

    manifest = await runtime.artifacts.create_from_path(
        "artifacts/report.txt",
        context_id=context.session_id,
        session_id=context.session_id,
        name="report",
        role=ArtifactRole.BODY,
        mime_type="text/plain",
        metadata={"kind": "demo"},
    )
    assert manifest.body_uri.endswith("/body")
    assert runtime.artifacts.resolve(manifest.manifest_uri).artifact_id == manifest.artifact_id
    assert await runtime.artifacts.read_body(manifest.artifact_id, start=2, length=3) == b"cde"
    assert '"name": "report"' in str(await context.read_resource(manifest.manifest_uri))
