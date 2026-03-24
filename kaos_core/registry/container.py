from __future__ import annotations

from contextvars import ContextVar

from kaos_core.artifacts import ArtifactStore
from kaos_core.config import KaosSettings
from kaos_core.registry.namespace import NamespaceManager
from kaos_core.registry.prompt_registry import PromptRegistry
from kaos_core.registry.resource_registry import ResourceRegistry
from kaos_core.registry.tool_registry import ToolRegistry
from kaos_core.vfs.core import VirtualFileSystem

_default_runtime: ContextVar[KaosRuntime | None] = ContextVar("kaos_default_runtime", default=None)


class KaosRuntime:
    def __init__(self, config: KaosSettings | None = None) -> None:
        self.settings = config or KaosSettings()
        self.namespaces = NamespaceManager()
        self.tools = ToolRegistry(namespace_manager=self.namespaces)
        self.resources = ResourceRegistry()
        self.prompts = PromptRegistry()
        self.vfs = VirtualFileSystem()
        self.artifacts = ArtifactStore(
            self.vfs,
            manifest_context_id=self.settings.artifact_manifest_context_id,
            manifest_prefix=self.settings.artifact_manifest_prefix,
            max_inline_read_bytes=self.settings.artifact_inline_read_max_bytes,
            default_chunk_size=self.settings.artifact_chunk_size_bytes,
            temporary_ttl_seconds=self.settings.artifact_temporary_ttl_seconds,
        )

    @classmethod
    def default(cls) -> KaosRuntime:
        runtime = _default_runtime.get()
        if runtime is None:
            runtime = cls()
            _default_runtime.set(runtime)
        return runtime

    @classmethod
    def set_default(cls, runtime: KaosRuntime) -> None:
        _default_runtime.set(runtime)

    async def shutdown(self) -> None:
        for tool in self.tools.list_tool_objects():
            await tool.shutdown()
