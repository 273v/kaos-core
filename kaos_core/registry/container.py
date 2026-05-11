from __future__ import annotations

from contextvars import ContextVar
from functools import cached_property
from typing import Any

from kaos_core.artifacts import ArtifactStore
from kaos_core.config import KaosSettings
from kaos_core.registry.namespace import NamespaceManager
from kaos_core.registry.prompt_registry import PromptRegistry
from kaos_core.registry.resource_registry import ResourceRegistry
from kaos_core.registry.tool_registry import ToolRegistry
from kaos_core.types.enums import IsolationMode, StorageBackend
from kaos_core.vfs.core import VirtualFileSystem
from kaos_core.vfs.models import VFSConfig

_default_runtime: ContextVar[KaosRuntime | None] = ContextVar("kaos_default_runtime", default=None)


class KaosRuntime:
    """KAOS execution container.

    Holds the tool/resource/prompt registries, ``settings``, a
    :class:`VirtualFileSystem`, and an :class:`ArtifactStore`. The
    artifact store is a :class:`cached_property` over ``self.vfs`` so
    callers that swap the VFS post-init (e.g. test fixtures replacing
    a disk-backed VFS with an in-memory one) get a fresh
    ``ArtifactStore`` automatically without rebuilding constructor
    keywords by hand.

    The cross-run isolation hazard the lazy-rebuild guards against:
    the default VFS backend is :attr:`StorageBackend.DISK` rooted at
    ``.kaos-vfs`` — session memory persists across pytest invocations,
    which silently false-greens live composition tests on second-and-
    later runs (the agent "answers from memory" instead of calling its
    tools).

    Inject an in-memory VFS for pytest with::

        runtime = KaosRuntime.test_mode()           # in-memory, isolated
        runtime = KaosRuntime(vfs=my_custom_vfs)    # bring your own
    """

    def __init__(
        self,
        config: KaosSettings | None = None,
        *,
        vfs: VirtualFileSystem | None = None,
    ) -> None:
        self.settings = config or KaosSettings()
        self.namespaces = NamespaceManager()
        self.tools = ToolRegistry(namespace_manager=self.namespaces)
        self.resources = ResourceRegistry()
        self.prompts = PromptRegistry()
        self._vfs: VirtualFileSystem = vfs if vfs is not None else VirtualFileSystem()
        self.module_settings: dict[str, Any] = {}

    @property
    def vfs(self) -> VirtualFileSystem:
        """Active virtual file system.

        Setting this property invalidates the cached
        :attr:`artifacts` store so the next read reflects the new
        VFS — eliminating the post-init "rebuild the ArtifactStore
        with all five constructor params" footgun that pre-dated this
        property.
        """
        return self._vfs

    @vfs.setter
    def vfs(self, value: VirtualFileSystem) -> None:
        self._vfs = value
        # Invalidate the cached artifacts so the next access rebuilds
        # against the new VFS. ``cached_property`` stores the cached
        # value in the instance __dict__ under the property name; we
        # pop unconditionally so the swap is correct whether or not
        # the property has been read yet.
        self.__dict__.pop("artifacts", None)

    @cached_property
    def artifacts(self) -> ArtifactStore:
        """ArtifactStore lazily bound to the current ``self.vfs``.

        Built on first access and cached. Cache is invalidated when
        ``self.vfs`` is reassigned, so ``runtime.artifacts.vfs`` is
        always the live VFS — even after a fixture swap.
        """
        return ArtifactStore(
            self._vfs,
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

    @classmethod
    def test_mode(cls, in_memory: bool = True) -> KaosRuntime:
        """Canonical pytest constructor with isolated VFS.

        Returns a fresh :class:`KaosRuntime` whose VFS is in-memory
        (default) and globally scoped so each test gets a clean slate.
        The ``in_memory=False`` form still constructs a fresh disk
        VFS rooted at ``.kaos-vfs`` but with :attr:`IsolationMode.GLOBAL`
        — useful for tests that need a real disk backend but should
        not collide with the default runtime singleton.

        Use in place of ``KaosRuntime()`` in any pytest fixture where
        the default disk-backed, context-isolated VFS would leak
        session memory across pytest invocations.
        """
        backend = StorageBackend.MEMORY if in_memory else StorageBackend.DISK
        config = VFSConfig(
            default_backend=backend,
            isolation_mode=IsolationMode.GLOBAL,
        )
        return cls(vfs=VirtualFileSystem(config=config))

    async def shutdown(self) -> None:
        for tool in self.tools.list_tool_objects():
            await tool.shutdown()
