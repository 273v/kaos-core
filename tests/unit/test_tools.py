"""Unit tests for kaos-core MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kaos_core import (
    KaosContext,
    KaosRuntime,
    KaosSettings,
    KaosTool,
    VFSConfig,
    VirtualFileSystem,
)
from kaos_core.artifacts import ArtifactStore
from kaos_core.tools import (
    ArtifactsInspectTool,
    ArtifactsListTool,
    ConfigShowTool,
    CredentialsCheckTool,
    ListResourcesTool,
    ListToolsTool,
    ToolSchemaTool,
    VFSListTool,
    VFSReadTool,
    VFSStatTool,
    register_core_tools,
)
from kaos_core.types.enums import StorageBackend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOOL_CLASSES: list[type[KaosTool]] = [
    ListToolsTool,
    ToolSchemaTool,
    ListResourcesTool,
    VFSListTool,
    VFSReadTool,
    VFSStatTool,
    ArtifactsListTool,
    ArtifactsInspectTool,
    ConfigShowTool,
    CredentialsCheckTool,
]


def _make_runtime(tmp_path: Path) -> KaosRuntime:
    """Create a runtime with disk-backed VFS for testing."""
    settings = KaosSettings(credential_store_path=tmp_path / "creds.json")
    runtime = KaosRuntime(config=settings)
    runtime.vfs = VirtualFileSystem(
        VFSConfig(default_backend=StorageBackend.DISK, disk_base_path=tmp_path / "vfs")
    )
    runtime.artifacts = ArtifactStore(
        runtime.vfs,
        manifest_context_id=settings.artifact_manifest_context_id,
        manifest_prefix=settings.artifact_manifest_prefix,
    )
    return runtime


def _make_context(runtime: KaosRuntime) -> KaosContext:
    return KaosContext.create(session_id="test-session", runtime=runtime)


# ---------------------------------------------------------------------------
# Metadata validation
# ---------------------------------------------------------------------------


class TestToolMetadata:
    """Verify tool metadata is correctly defined for all tools."""

    @pytest.mark.parametrize("tool_cls", TOOL_CLASSES)
    def test_tool_name_matches_pattern(self, tool_cls: type[KaosTool]) -> None:
        tool = tool_cls()
        meta = tool.metadata
        assert meta.name.startswith("kaos-core-"), f"{meta.name} must start with 'kaos-core-'"
        assert meta.module_name == "kaos-core"
        # Pin the contract that tool metadata version tracks the package
        # version, not a hardcoded literal. audit-04/kaos-core.md F-001
        # caught this drifting in earlier releases.
        from kaos_core import __version__

        assert meta.version == __version__

    @pytest.mark.parametrize("tool_cls", TOOL_CLASSES)
    def test_annotations_are_set(self, tool_cls: type[KaosTool]) -> None:
        tool = tool_cls()
        ann = tool.metadata.annotations
        assert ann is not None, f"{tool.metadata.name} must set annotations"
        assert ann.readOnlyHint is True
        assert ann.destructiveHint is False
        assert ann.idempotentHint is True
        assert ann.openWorldHint is False

    @pytest.mark.parametrize("tool_cls", TOOL_CLASSES)
    def test_description_nonempty(self, tool_cls: type[KaosTool]) -> None:
        tool = tool_cls()
        assert len(tool.metadata.description) > 10

    @pytest.mark.parametrize("tool_cls", TOOL_CLASSES)
    def test_json_schema_valid(self, tool_cls: type[KaosTool]) -> None:
        tool = tool_cls()
        schema = tool.get_json_schema()
        assert schema["type"] == "object"
        assert "properties" in schema


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_core_tools_count(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        count = register_core_tools(runtime)
        assert count == 10

    def test_register_core_tools_listed(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        register_core_tools(runtime)
        names = runtime.tools.list_tools()
        expected = {
            "kaos-core-list-tools",
            "kaos-core-tool-schema",
            "kaos-core-list-resources",
            "kaos-core-vfs-list",
            "kaos-core-vfs-read",
            "kaos-core-vfs-stat",
            "kaos-core-artifacts-list",
            "kaos-core-artifacts-inspect",
            "kaos-core-config-show",
            "kaos-core-credentials-check",
        }
        assert expected.issubset(set(names))


# ---------------------------------------------------------------------------
# Error cases: no context
# ---------------------------------------------------------------------------


class TestNoContext:
    """All tools needing runtime should return a helpful error with no context."""

    @pytest.mark.parametrize(
        "tool_cls",
        [
            ListToolsTool,
            ToolSchemaTool,
            ListResourcesTool,
            VFSListTool,
            VFSReadTool,
            VFSStatTool,
            ArtifactsListTool,
            ArtifactsInspectTool,
            ConfigShowTool,
        ],
    )
    async def test_no_context_returns_error(self, tool_cls: type[KaosTool]) -> None:
        tool = tool_cls()
        result = await tool.execute({}, context=None)
        assert result.isError
        assert "runtime" in (result.text or "").lower()

    @pytest.mark.parametrize(
        "tool_cls",
        [
            ListToolsTool,
            ToolSchemaTool,
            ListResourcesTool,
            VFSListTool,
            VFSReadTool,
            VFSStatTool,
            ArtifactsListTool,
            ArtifactsInspectTool,
            ConfigShowTool,
        ],
    )
    async def test_no_runtime_on_context_returns_error(self, tool_cls: type[KaosTool]) -> None:
        tool = tool_cls()
        ctx = KaosContext.create(session_id="test", runtime=None)
        result = await tool.execute({}, context=ctx)
        assert result.isError


# ---------------------------------------------------------------------------
# ListToolsTool
# ---------------------------------------------------------------------------


class TestListToolsTool:
    async def test_list_all(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        register_core_tools(runtime)
        ctx = _make_context(runtime)

        tool = ListToolsTool()
        result = await tool.execute({}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert data["total_matches"] == 10
        assert len(data["tools"]) == 10

    async def test_filter_by_category(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        register_core_tools(runtime)
        ctx = _make_context(runtime)

        tool = ListToolsTool()
        result = await tool.execute({"category": "utility"}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        for t in data["tools"]:
            assert t["category"] == "utility"

    async def test_filter_by_query(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        register_core_tools(runtime)
        ctx = _make_context(runtime)

        tool = ListToolsTool()
        result = await tool.execute({"query": "VFS"}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert data["total_matches"] >= 1

    async def test_invalid_category(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        register_core_tools(runtime)
        ctx = _make_context(runtime)

        tool = ListToolsTool()
        result = await tool.execute({"category": "nonexistent"}, context=ctx)
        assert result.isError
        assert "Invalid category" in (result.text or "")


# ---------------------------------------------------------------------------
# ToolSchemaTool
# ---------------------------------------------------------------------------


class TestToolSchemaTool:
    async def test_get_schema(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        register_core_tools(runtime)
        ctx = _make_context(runtime)

        tool = ToolSchemaTool()
        result = await tool.execute({"name": "kaos-core-list-tools"}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert "schema" in data
        assert data["schema"]["type"] == "object"

    async def test_tool_not_found(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        register_core_tools(runtime)
        ctx = _make_context(runtime)

        tool = ToolSchemaTool()
        result = await tool.execute({"name": "kaos-core-does-not-exist"}, context=ctx)
        assert result.isError
        assert "not found" in (result.text or "").lower()
        assert "kaos-core-list-tools" in (result.text or "")


# ---------------------------------------------------------------------------
# ListResourcesTool
# ---------------------------------------------------------------------------


class TestListResourcesTool:
    async def test_list_empty(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)

        tool = ListResourcesTool()
        result = await tool.execute({}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert data["total_matches"] == 0

    async def test_invalid_resource_type(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)

        tool = ListResourcesTool()
        result = await tool.execute({"resource_type": "bogus"}, context=ctx)
        assert result.isError
        assert "Invalid resource_type" in (result.text or "")


# ---------------------------------------------------------------------------
# VFS tools
# ---------------------------------------------------------------------------


class TestVFSListTool:
    async def test_list_empty_vfs(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)

        tool = VFSListTool()
        result = await tool.execute({}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert data["count"] == 0
        assert data["has_more"] is False

    async def test_list_with_files(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)
        # Write into the calling session's VFS scope so the
        # session-scoped VFS list tool sees it.
        await runtime.vfs.write("test.txt", b"hello world", context_id=ctx.session_id)

        tool = VFSListTool()
        result = await tool.execute({"limit": 10}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert data["count"] >= 1

    async def test_list_uses_cursor_for_second_page(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)
        for index in range(3):
            await runtime.vfs.write(
                f"file-{index}.txt",
                f"item {index}".encode(),
                context_id=ctx.session_id,
            )

        tool = VFSListTool()
        first = await tool.execute({"limit": 2}, context=ctx)
        first_data = first.require_structured()
        assert first_data["has_more"] is True
        assert first_data["next_cursor"] == "2"

        second = await tool.execute({"limit": 2, "cursor": first_data["next_cursor"]}, context=ctx)
        second_data = second.require_structured()
        assert second_data["items"] == ["file-2.txt"]
        assert second_data["has_more"] is False


class TestVFSReadTool:
    async def test_read_text_file(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)
        await runtime.vfs.write("hello.txt", b"hello world", context_id=ctx.session_id)

        tool = VFSReadTool()
        result = await tool.execute({"path": "hello.txt"}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert data["content"] == "hello world"
        assert data["encoding"] == "utf-8"

    async def test_read_binary_file(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)
        binary_data = bytes(range(256))
        await runtime.vfs.write("data.bin", binary_data, context_id=ctx.session_id)

        tool = VFSReadTool()
        result = await tool.execute({"path": "data.bin"}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert data["encoding"] == "base64"

    async def test_read_nonexistent(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)

        tool = VFSReadTool()
        result = await tool.execute({"path": "no-such-file.txt"}, context=ctx)
        assert result.isError

    async def test_read_length_exceeds_limit(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)

        tool = VFSReadTool()
        result = await tool.execute({"path": "test.txt", "length": 300_000}, context=ctx)
        assert result.isError
        assert "256KB" in (result.text or "")


class TestVFSStatTool:
    async def test_stat_existing(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)
        await runtime.vfs.write("stat-test.txt", b"content here", context_id=ctx.session_id)

        tool = VFSStatTool()
        result = await tool.execute({"path": "stat-test.txt"}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert data["exists"] is True
        assert data["size"] == 12
        assert data["kind"] == "file"

    async def test_stat_missing(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)

        tool = VFSStatTool()
        result = await tool.execute({"path": "missing.txt"}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert data["exists"] is False


# ---------------------------------------------------------------------------
# Artifacts tools
# ---------------------------------------------------------------------------


class TestArtifactsListTool:
    async def test_list_empty(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)

        tool = ArtifactsListTool()
        result = await tool.execute({}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert data["total_matches"] == 0

    async def test_list_with_artifacts(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)

        # Write a file and create an artifact
        await runtime.vfs.write("doc.txt", b"document content", context_id="ctx1")
        await runtime.artifacts.create_from_path(
            "doc.txt",
            context_id="ctx1",
            session_id="test-session",
            name="test-doc",
        )

        tool = ArtifactsListTool()
        result = await tool.execute({}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert data["total_matches"] == 1
        assert data["artifacts"][0]["name"] == "test-doc"


class TestArtifactsInspectTool:
    async def test_inspect_existing(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)

        await runtime.vfs.write("doc.txt", b"document content", context_id="ctx1")
        manifest = await runtime.artifacts.create_from_path(
            "doc.txt",
            context_id="ctx1",
            session_id="test-session",
            name="test-doc",
        )

        tool = ArtifactsInspectTool()
        result = await tool.execute({"artifact_id": manifest.artifact_id}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert data["name"] == "test-doc"
        assert data["artifact_id"] == manifest.artifact_id

    async def test_inspect_not_found(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)

        tool = ArtifactsInspectTool()
        result = await tool.execute({"artifact_id": "nonexistent-id"}, context=ctx)
        assert result.isError
        assert "not found" in (result.text or "").lower()


# ---------------------------------------------------------------------------
# ConfigShowTool
# ---------------------------------------------------------------------------


class TestConfigShowTool:
    async def test_show_config(self, tmp_path: Path) -> None:
        runtime = _make_runtime(tmp_path)
        ctx = _make_context(runtime)

        tool = ConfigShowTool()
        result = await tool.execute({}, context=ctx)
        assert not result.isError
        data = result.require_structured()
        assert "log_level" in data
        assert "timeout" in data

    async def test_secrets_are_redacted(self, tmp_path: Path) -> None:
        """Verify _redact_secrets works on nested secret-like fields."""
        from kaos_core.tools import _redact_secrets

        d: dict[str, Any] = {
            "api_key": "real-value",
            "log_level": "INFO",
            "nested": {"password": "hunter2", "name": "ok"},
        }
        _redact_secrets(d)
        assert d["api_key"] == "***REDACTED***"
        assert d["log_level"] == "INFO"
        assert d["nested"]["password"] == "***REDACTED***"
        assert d["nested"]["name"] == "ok"


# ---------------------------------------------------------------------------
# CredentialsCheckTool
# ---------------------------------------------------------------------------


class TestCredentialsCheckTool:
    async def test_requires_runtime_context(self, tmp_path: Path) -> None:
        """Without an authenticated runtime/context the tool MUST refuse.

        This closes the credential-surface enumeration recon channel
        reported in the audit: an unauthenticated caller previously
        could probe `module/service/key` triples and learn which were
        configured, even though no values were returned.
        """
        tool = CredentialsCheckTool()
        result = await tool.execute(
            {"module": "kaos-web", "service": "serpapi"},
            context=None,
        )
        assert result.isError
        assert result.text is not None
        assert "kaos-core-serve" not in result.text
        assert "kaos-mcp" in result.text

    async def test_credential_not_found(self, tmp_path: Path) -> None:
        tool = CredentialsCheckTool()
        runtime = _make_runtime(tmp_path)
        context = _make_context(runtime)
        result = await tool.execute(
            {"module": "kaos-web", "service": "serpapi"},
            context=context,
        )
        assert not result.isError
        data = result.require_structured()
        assert data["module"] == "kaos-web"
        assert data["service"] == "serpapi"
        assert data["key"] == "default"
        assert data["exists"] is False

    async def test_credential_found(self, tmp_path: Path) -> None:
        from kaos_core.config.credentials import CredentialStore

        runtime = _make_runtime(tmp_path)
        store = CredentialStore(path=runtime.settings.credential_store_path)
        store.set("test-mod", "test-svc", "default", "secret-value")

        tool = CredentialsCheckTool()
        context = _make_context(runtime)

        result = await tool.execute(
            {"module": "test-mod", "service": "test-svc"},
            context=context,
        )
        assert not result.isError
        data = result.require_structured()
        assert data["exists"] is True
        # Verify the actual value is NEVER exposed
        result_text = result.text or ""
        assert "secret-value" not in result_text

    async def test_credential_path_can_be_overridden_by_context(self, tmp_path: Path) -> None:
        from kaos_core.config.credentials import CredentialStore

        override_path = tmp_path / "override-creds.json"
        store = CredentialStore(path=override_path)
        store.set("override-mod", "override-svc", "default", "secret-value")

        tool = CredentialsCheckTool()
        runtime = _make_runtime(tmp_path)
        context = _make_context(runtime)
        context.set_config("credential_store_path", override_path)

        result = await tool.execute(
            {"module": "override-mod", "service": "override-svc"},
            context=context,
        )

        assert not result.isError
        data = result.require_structured()
        assert data["exists"] is True
