"""MCP tool definitions for kaos-core runtime introspection.

KaosTool implementations for agent self-awareness, VFS browsing,
artifact inspection, and configuration display. All tools are
read-only, local, and idempotent.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from kaos_core.artifacts.models import SUMMARY_THRESHOLD
from kaos_core.base.context import KaosContext
from kaos_core.base.tool import KaosTool
from kaos_core.config.credentials import CredentialStore
from kaos_core.exceptions import ResourceError
from kaos_core.logging import get_logger
from kaos_core.types.annotations import ToolAnnotations
from kaos_core.types.enums import ToolCapability, ToolCategory
from kaos_core.types.metadata import ToolMetadata
from kaos_core.types.parameters import ParameterSchema
from kaos_core.types.results import ToolResult

logger = get_logger(__name__)

_MODULE = "kaos-core"
_VERSION = "0.1.0"

# All core tools are read-only, idempotent, and local-only (no external services).
_CORE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

_NO_RUNTIME_ERROR = (
    "No runtime context. This tool requires a running KAOS server. "
    "Expose the runtime through the companion 'kaos-mcp' package or register tools "
    "with a KaosRuntime before calling this tool."
)

_CATEGORY_ENUM = [e.value for e in ToolCategory]
_CAPABILITY_ENUM = [e.value for e in ToolCapability]


def _credential_store_from_context(context: KaosContext) -> CredentialStore:
    path = context.get_config("credential_store_path")
    return CredentialStore(path=Path(path) if path is not None else None)


class ListToolsTool(KaosTool):
    """List and search registered MCP tools."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="kaos-core-list-tools",
            display_name="List Tools",
            description=(
                "List registered MCP tools with optional filtering by category, "
                "capability, namespace, or text query. Use this to discover available "
                "tools and their capabilities."
            ),
            category=ToolCategory.UTILITY,
            capability=ToolCapability.QUERY,
            module_name=_MODULE,
            version=_VERSION,
            annotations=_CORE_ANNOTATIONS,
            input_schema=[
                ParameterSchema(
                    name="category",
                    type="string",
                    description="Filter by tool category.",
                    required=False,
                    constraints={"enum": _CATEGORY_ENUM},
                ),
                ParameterSchema(
                    name="capability",
                    type="string",
                    description="Filter by tool capability.",
                    required=False,
                    constraints={"enum": _CAPABILITY_ENUM},
                ),
                ParameterSchema(
                    name="namespace",
                    type="string",
                    description="Filter by namespace prefix (e.g. 'kaos-pdf').",
                    required=False,
                ),
                ParameterSchema(
                    name="query",
                    type="string",
                    description="Text search in tool names and descriptions.",
                    required=False,
                ),
            ],
        )

    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        if context is None or context.runtime is None:
            return ToolResult.create_error(_NO_RUNTIME_ERROR)

        category = inputs.get("category")
        capability = inputs.get("capability")
        namespace = inputs.get("namespace")
        query = inputs.get("query")

        try:
            cat_enum = ToolCategory(category) if category else None
        except ValueError:
            return ToolResult.create_error(
                f"Invalid category '{category}'. Valid values: {', '.join(_CATEGORY_ENUM)}"
            )

        try:
            cap_enum = ToolCapability(capability) if capability else None
        except ValueError:
            return ToolResult.create_error(
                f"Invalid capability '{capability}'. Valid values: {', '.join(_CAPABILITY_ENUM)}"
            )

        results = context.runtime.tools.search_tools(
            category=cat_enum,
            capability=cap_enum,
            namespace=namespace,
            query=query,
        )

        tool_dicts = [
            {
                "name": m.name,
                "display_name": m.display_name,
                "description": m.description,
                "category": m.category.value,
                "capability": m.capability.value,
                "module_name": m.module_name,
            }
            for m in results
        ]

        summary = f"Found {len(tool_dicts)} tool(s)"
        if query:
            summary += f" matching '{query}'"
        return ToolResult.create_success(
            output={"tools": tool_dicts, "total_matches": len(tool_dicts)},
            summary=summary,
        )


class ToolSchemaTool(KaosTool):
    """Get the JSON schema for a specific tool's inputs."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="kaos-core-tool-schema",
            display_name="Tool Schema",
            description=(
                "Get the JSON input schema for a registered MCP tool. "
                "Use kaos-core-list-tools first to discover tool names."
            ),
            category=ToolCategory.UTILITY,
            capability=ToolCapability.QUERY,
            module_name=_MODULE,
            version=_VERSION,
            annotations=_CORE_ANNOTATIONS,
            input_schema=[
                ParameterSchema(
                    name="name",
                    type="string",
                    description="Full tool name (e.g. 'kaos-pdf-extract-parse').",
                ),
            ],
        )

    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        if context is None or context.runtime is None:
            return ToolResult.create_error(_NO_RUNTIME_ERROR)

        name = inputs["name"]
        schema = context.runtime.tools.get_tool_schema(name)
        if schema is None:
            return ToolResult.create_error(
                f"Tool '{name}' not found. Use kaos-core-list-tools to see available tools."
            )

        return ToolResult.create_success(
            output={"name": name, "schema": schema},
            summary=f"Schema for '{name}'",
        )


class ListResourcesTool(KaosTool):
    """List registered MCP resources."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="kaos-core-list-resources",
            display_name="List Resources",
            description=(
                "List registered MCP resources with optional filtering by type, "
                "module, or text query."
            ),
            category=ToolCategory.UTILITY,
            capability=ToolCapability.QUERY,
            module_name=_MODULE,
            version=_VERSION,
            annotations=_CORE_ANNOTATIONS,
            input_schema=[
                ParameterSchema(
                    name="resource_type",
                    type="string",
                    description="Filter by resource type.",
                    required=False,
                ),
                ParameterSchema(
                    name="module",
                    type="string",
                    description="Filter by provider module name.",
                    required=False,
                ),
                ParameterSchema(
                    name="query",
                    type="string",
                    description="Text search in resource names and descriptions.",
                    required=False,
                ),
            ],
        )

    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        if context is None or context.runtime is None:
            return ToolResult.create_error(_NO_RUNTIME_ERROR)

        from kaos_core.types.enums import ResourceType

        resource_type_str = inputs.get("resource_type")
        module = inputs.get("module")
        query = inputs.get("query")

        rt_enum = None
        if resource_type_str:
            try:
                rt_enum = ResourceType(resource_type_str)
            except ValueError:
                valid = ", ".join(e.value for e in ResourceType)
                return ToolResult.create_error(
                    f"Invalid resource_type '{resource_type_str}'. Valid values: {valid}"
                )

        results = context.runtime.resources.search_resources(
            resource_type=rt_enum,
            module=module,
            query=query,
        )

        resource_dicts = [
            {
                "uri": m.uri,
                "name": m.name,
                "description": m.description,
                "resource_type": m.resource_type.value,
                "provider_module": m.provider_module,
                "mime_type": m.mime_type,
            }
            for m in results
        ]

        summary = f"Found {len(resource_dicts)} resource(s)"
        return ToolResult.create_success(
            output={"resources": resource_dicts, "total_matches": len(resource_dicts)},
            summary=summary,
        )


class VFSListTool(KaosTool):
    """List files in the Virtual File System."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="kaos-core-vfs-list",
            display_name="VFS List",
            description=(
                "List files in the Virtual File System at a given path prefix. "
                "Returns paginated results."
            ),
            category=ToolCategory.DATA,
            capability=ToolCapability.QUERY,
            module_name=_MODULE,
            version=_VERSION,
            annotations=_CORE_ANNOTATIONS,
            input_schema=[
                ParameterSchema(
                    name="path",
                    type="string",
                    description="Path prefix to list (default: root).",
                    required=False,
                    default="",
                ),
                ParameterSchema(
                    name="limit",
                    type="integer",
                    description="Maximum items to return (default: 50).",
                    required=False,
                    default=50,
                ),
            ],
        )

    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        if context is None or context.runtime is None:
            return ToolResult.create_error(_NO_RUNTIME_ERROR)

        path = inputs.get("path", "")
        limit = inputs.get("limit", 50)

        try:
            # Pass context.session_id so a tool listing the VFS only
            # sees its own session's namespace. Without this scope the
            # tool would operate on the shared default scope while
            # `context.get_vfs_path()` writes through the session
            # scope — an isolation bug that hides session writes
            # behind a permissive default view.
            page = await context.runtime.vfs.list_page(
                path, limit=limit, context_id=context.session_id
            )
        except Exception as exc:
            return ToolResult.create_error(
                f"VFS list failed for path '{path}': {exc}. "
                "Verify the path is valid. Use kaos-core-vfs-list with path='' to see root."
            )

        has_more = page.next_cursor is not None
        output = {
            "path": path,
            "items": page.items,
            "count": len(page.items),
            "has_more": has_more,
        }
        if has_more:
            output["next_cursor"] = page.next_cursor

        summary = f"{len(page.items)} item(s) at '{path or '/'}'"
        if has_more:
            summary += " (more available)"
        return ToolResult.create_success(output=output, summary=summary)


class VFSReadTool(KaosTool):
    """Read file content from the Virtual File System."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="kaos-core-vfs-read",
            display_name="VFS Read",
            description=(
                "Read file content from the Virtual File System. "
                "Supports range reads with start/length. Max read: 256KB. "
                "Text files are returned as UTF-8; binary files as base64."
            ),
            category=ToolCategory.DATA,
            capability=ToolCapability.EXTRACT,
            module_name=_MODULE,
            version=_VERSION,
            annotations=_CORE_ANNOTATIONS,
            input_schema=[
                ParameterSchema(
                    name="path",
                    type="string",
                    description="Path to the file in VFS.",
                ),
                ParameterSchema(
                    name="start",
                    type="integer",
                    description="Byte offset to start reading from (default: 0).",
                    required=False,
                    default=0,
                ),
                ParameterSchema(
                    name="length",
                    type="integer",
                    description=(
                        "Number of bytes to read. Omit to read the full file "
                        f"(up to {SUMMARY_THRESHOLD} bytes)."
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        if context is None or context.runtime is None:
            return ToolResult.create_error(_NO_RUNTIME_ERROR)

        path = inputs["path"]
        start = inputs.get("start", 0)
        length = inputs.get("length")

        # Enforce max read size
        if length is not None and length > SUMMARY_THRESHOLD:
            return ToolResult.create_error(
                f"Requested read length ({length}) exceeds the 256KB limit. "
                "Use a smaller length or read in chunks."
            )

        effective_length = length if length is not None else SUMMARY_THRESHOLD

        try:
            # Scope the read to the calling session's VFS namespace
            # to match what `context.get_vfs_path()` writes through.
            data = await context.runtime.vfs.read_range(
                path,
                start=start,
                length=effective_length,
                context_id=context.session_id,
            )
        except FileNotFoundError:
            return ToolResult.create_error(
                f"File not found: '{path}'. Use kaos-core-vfs-list to browse available files."
            )
        except Exception as exc:
            return ToolResult.create_error(
                f"VFS read failed for '{path}': {exc}. Check the path with kaos-core-vfs-stat."
            )

        # Try UTF-8 decode, fall back to base64 for binary
        try:
            text = data.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text = base64.b64encode(data).decode("ascii")
            encoding = "base64"

        return ToolResult.create_success(
            output={
                "path": path,
                "content": text,
                "encoding": encoding,
                "size": len(data),
                "start": start,
            },
            summary=f"Read {len(data)} bytes from '{path}' ({encoding})",
        )


class VFSStatTool(KaosTool):
    """Get metadata about a VFS file."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="kaos-core-vfs-stat",
            display_name="VFS Stat",
            description=(
                "Get metadata (existence, size, type, timestamps) for a file "
                "in the Virtual File System."
            ),
            category=ToolCategory.DATA,
            capability=ToolCapability.QUERY,
            module_name=_MODULE,
            version=_VERSION,
            annotations=_CORE_ANNOTATIONS,
            input_schema=[
                ParameterSchema(
                    name="path",
                    type="string",
                    description="Path to the file in VFS.",
                ),
            ],
        )

    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        if context is None or context.runtime is None:
            return ToolResult.create_error(_NO_RUNTIME_ERROR)

        path = inputs["path"]

        try:
            stat = await context.runtime.vfs.stat(path, context_id=context.session_id)
        except Exception as exc:
            return ToolResult.create_error(
                f"VFS stat failed for '{path}': {exc}. "
                "Use kaos-core-vfs-list to browse available files."
            )

        stat_dict = {
            "path": stat.path,
            "exists": stat.exists,
            "kind": stat.kind,
            "size": stat.size,
            "backend": stat.backend.value,
            "created_at": stat.created_at,
            "modified_at": stat.modified_at,
            "mime_type": stat.mime_type,
        }

        if stat.exists:
            summary = f"'{stat.path}': {stat.kind}, {stat.size} bytes"
        else:
            summary = f"'{stat.path}': does not exist"

        return ToolResult.create_success(output=stat_dict, summary=summary)


class ArtifactsListTool(KaosTool):
    """List stored artifacts in the calling session."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="kaos-core-artifacts-list",
            display_name="List Artifacts",
            description=(
                "List artifacts stored by the current session. Optionally filter by "
                "workflow_id. Cross-session listing is intentionally not exposed via "
                "this MCP tool — Python-API callers can pass session_id explicitly to "
                "ArtifactStore.list_artifacts when administrative access is needed."
            ),
            category=ToolCategory.DATA,
            capability=ToolCapability.QUERY,
            module_name=_MODULE,
            version=_VERSION,
            annotations=_CORE_ANNOTATIONS,
            input_schema=[
                ParameterSchema(
                    name="workflow_id",
                    type="string",
                    description="Filter by workflow ID.",
                    required=False,
                ),
            ],
        )

    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        if context is None or context.runtime is None:
            return ToolResult.create_error(_NO_RUNTIME_ERROR)

        workflow_id = inputs.get("workflow_id")

        # Scope strictly to the calling session. We deliberately ignore
        # any caller-supplied session_id — that input was historically
        # accepted but never authorised, allowing cross-session
        # enumeration through this tool.
        manifests = context.runtime.artifacts.list_artifacts(
            session_id=context.session_id,
            workflow_id=workflow_id,
        )

        artifact_dicts = [
            {
                "artifact_id": m.artifact_id,
                "name": m.name,
                "description": m.description,
                "uri": m.uri,
                "role": m.role.value,
                "size": m.size,
                "mime_type": m.mime_type,
                "created_at": m.created_at,
            }
            for m in manifests
        ]

        summary = f"Found {len(artifact_dicts)} artifact(s)"
        return ToolResult.create_success(
            output={"artifacts": artifact_dicts, "total_matches": len(artifact_dicts)},
            summary=summary,
        )


class ArtifactsInspectTool(KaosTool):
    """Inspect a specific artifact's metadata."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="kaos-core-artifacts-inspect",
            display_name="Inspect Artifact",
            description=(
                "Get full metadata for a specific artifact by ID. "
                "Returns all manifest fields except the body content. "
                "Use kaos-core-artifacts-list first to discover artifact IDs."
            ),
            category=ToolCategory.DATA,
            capability=ToolCapability.QUERY,
            module_name=_MODULE,
            version=_VERSION,
            annotations=_CORE_ANNOTATIONS,
            input_schema=[
                ParameterSchema(
                    name="artifact_id",
                    type="string",
                    description="The artifact ID to inspect.",
                ),
            ],
        )

    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        if context is None or context.runtime is None:
            return ToolResult.create_error(_NO_RUNTIME_ERROR)

        artifact_id = inputs["artifact_id"]

        try:
            # Scope to the calling session — `caller_session_id` makes
            # the store return a uniform "Unknown artifact" error for
            # any artifact owned by a different session, so cross-session
            # probing cannot distinguish "exists but forbidden" from
            # "does not exist".
            manifest = context.runtime.artifacts.get(
                artifact_id, caller_session_id=context.session_id
            )
        except ResourceError:
            logger.debug("Failed to get artifact '%s'", artifact_id, exc_info=True)
            return ToolResult.create_error(
                f"Artifact '{artifact_id}' not found. "
                "Use kaos-core-artifacts-list to see available artifacts."
            )

        manifest_dict = manifest.model_dump(mode="json")
        summary = (
            f"Artifact '{manifest.name}': {manifest.size} bytes, "
            f"role={manifest.role.value}, type={manifest.mime_type}"
        )
        return ToolResult.create_success(output=manifest_dict, summary=summary)


class ConfigShowTool(KaosTool):
    """Show current KAOS runtime configuration."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="kaos-core-config-show",
            display_name="Show Config",
            description=(
                "Show the current KAOS runtime configuration. "
                "Secret values (API keys, passwords) are redacted."
            ),
            category=ToolCategory.UTILITY,
            capability=ToolCapability.QUERY,
            module_name=_MODULE,
            version=_VERSION,
            annotations=_CORE_ANNOTATIONS,
            input_schema=[],
        )

    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        if context is None or context.runtime is None:
            return ToolResult.create_error(_NO_RUNTIME_ERROR)

        settings_dict = context.runtime.settings.model_dump(mode="json")
        _redact_secrets(settings_dict)

        summary = f"KAOS configuration ({len(settings_dict)} settings)"
        return ToolResult.create_success(output=settings_dict, summary=summary)


class CredentialsCheckTool(KaosTool):
    """Check whether a credential exists without revealing its value."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="kaos-core-credentials-check",
            display_name="Check Credentials",
            description=(
                "Check whether a credential is configured for a given module and service. "
                "Returns existence only -- NEVER reveals the credential value."
            ),
            category=ToolCategory.UTILITY,
            capability=ToolCapability.QUERY,
            module_name=_MODULE,
            version=_VERSION,
            annotations=_CORE_ANNOTATIONS,
            input_schema=[
                ParameterSchema(
                    name="module",
                    type="string",
                    description="Module name (e.g. 'kaos-web', 'kaos-source').",
                ),
                ParameterSchema(
                    name="service",
                    type="string",
                    description="Service name (e.g. 'serpapi', 'govinfo').",
                ),
                ParameterSchema(
                    name="key",
                    type="string",
                    description="Credential key (default: 'default').",
                    required=False,
                    default="default",
                ),
            ],
        )

    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        # Require an authenticated runtime/context. Without this gate
        # an unauthenticated MCP caller could enumerate the credential
        # surface — which modules, services, and keys are configured —
        # even though no values are returned. Closes the recon
        # side-channel reported in the audit.
        if context is None or context.runtime is None:
            return ToolResult.create_error(_NO_RUNTIME_ERROR)

        module = inputs["module"]
        service = inputs["service"]
        key = inputs.get("key", "default")

        store = _credential_store_from_context(context)
        exists = store.get(module, service, key) is not None

        result_dict = {
            "module": module,
            "service": service,
            "key": key,
            "exists": exists,
        }

        status = "configured" if exists else "not configured"
        summary = f"Credential {module}/{service}/{key}: {status}"
        return ToolResult.create_success(output=result_dict, summary=summary)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET_KEYWORDS = {"secret", "key", "password", "token", "credential", "api_key"}


def _redact_secrets(d: dict[str, Any]) -> None:
    """Redact values whose keys suggest they contain secrets."""
    for k in list(d):
        lower_key = k.lower()
        if any(word in lower_key for word in _SECRET_KEYWORDS):
            if d[k] is not None:
                d[k] = "***REDACTED***"
        elif isinstance(d[k], dict):
            _redact_secrets(d[k])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_core_tools(runtime: Any) -> int:
    """Register all kaos-core MCP tools with the runtime. Returns count."""
    tools: list[KaosTool] = [
        ListToolsTool(),
        ToolSchemaTool(),
        ListResourcesTool(),
        VFSListTool(),
        VFSReadTool(),
        VFSStatTool(),
        ArtifactsListTool(),
        ArtifactsInspectTool(),
        ConfigShowTool(),
        CredentialsCheckTool(),
    ]
    for tool in tools:
        runtime.tools.register_tool(tool)
    return len(tools)
