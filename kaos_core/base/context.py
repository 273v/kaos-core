from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from kaos_core.exceptions import RegistryError
from kaos_core.logging import ContextFilter, get_logger
from kaos_core.protocol.capabilities import ClientCapabilities
from kaos_core.protocol.initialize import InitializeRequest, InitializeResult
from kaos_core.protocol.roots import Root

ProgressCallback = Callable[[float, float | None, str | None], Awaitable[None] | None]


class KaosContext:
    def __init__(
        self,
        *,
        session_id: str,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        client_capabilities: Any = None,
        server_capabilities: Any = None,
        roots: list[Root] | None = None,
        protocol_version: str | None = None,
        runtime: Any = None,
        config: dict[str, Any] | None = None,
        vfs: Any = None,
    ) -> None:
        self.session_id = session_id
        self.trace_id = trace_id
        self.metadata = metadata or {}
        self.client_capabilities = client_capabilities
        self.server_capabilities = server_capabilities
        self.roots = roots
        self.protocol_version = protocol_version
        self.runtime = runtime
        self._config = config or {}
        self._vfs = vfs
        self._progress_callback: ProgressCallback | None = None
        self._logger = get_logger("kaos.context")
        self._logger.addFilter(ContextFilter(session_id=session_id, trace_id=trace_id))

    @classmethod
    def create(cls, session_id: str | None = None, **kwargs: Any) -> KaosContext:
        return cls(session_id=session_id or str(uuid4()), **kwargs)

    @classmethod
    def create_from_dict(cls, data: dict[str, Any]) -> KaosContext:
        return cls(**data)

    @classmethod
    def create_from_initialize(
        cls,
        init_result: InitializeResult,
        *,
        session_id: str | None = None,
        runtime: Any = None,
        init_request: InitializeRequest | None = None,
        client_capabilities: ClientCapabilities | None = None,
        roots: list[Root] | None = None,
    ) -> KaosContext:
        return cls(
            session_id=session_id or str(uuid4()),
            client_capabilities=(
                init_request.capabilities if init_request is not None else client_capabilities
            ),
            protocol_version=init_result.protocol_version,
            server_capabilities=init_result.capabilities,
            roots=roots,
            runtime=runtime,
        )

    @classmethod
    def create_test_context(cls) -> KaosContext:
        return cls.create(session_id="test-session", trace_id="test-trace")

    @property
    def vfs(self) -> Any:
        if self._vfs is None:
            if self.runtime is not None:
                self._vfs = self.runtime.vfs
            else:
                from kaos_core.vfs.core import VirtualFileSystem

                self._vfs = VirtualFileSystem()
        return self._vfs

    def supports_sampling(self) -> bool:
        return getattr(self.client_capabilities, "sampling", None) is not None

    def supports_elicitation(self) -> bool:
        return getattr(self.client_capabilities, "elicitation", None) is not None

    def supports_roots(self) -> bool:
        return getattr(self.client_capabilities, "roots", None) is not None

    def info(self, message: str, **kwargs: Any) -> None:
        self._logger.info(message, extra=kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._logger.warning(message, extra=kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._logger.error(message, extra=kwargs)

    async def report_progress(
        self,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        if self._progress_callback is None:
            return
        result = self._progress_callback(progress, total, message)
        if result is not None:
            await result

    def set_progress_callback(self, callback: ProgressCallback) -> None:
        self._progress_callback = callback

    def get_config(self, key: str, default: Any = None) -> Any:
        if key in self._config:
            return self._config[key]
        if self.runtime is not None and hasattr(self.runtime, "settings"):
            return getattr(self.runtime.settings, key, default)
        return default

    def set_config(self, key: str, value: Any) -> None:
        self._config[key] = value

    async def read_resource(self, uri: str) -> Any:
        if self.runtime is None:
            msg = "Context is not attached to a runtime"
            raise RuntimeError(msg)
        try:
            return await self.runtime.resources.get_resource(uri)
        except RegistryError:
            if hasattr(self.runtime, "artifacts"):
                return await self.runtime.artifacts.read_uri(uri, roots=self.roots)
            raise

    def get_vfs_path(self, path: str) -> Any:
        return self.vfs.get_path(path, context_id=self.session_id)

    def create_child_context(self, **kwargs: Any) -> KaosContext:
        child_metadata = {**self.metadata, **kwargs.pop("metadata", {})}
        return KaosContext(
            session_id=kwargs.pop("session_id", self.session_id),
            trace_id=kwargs.pop("trace_id", self.trace_id),
            metadata=child_metadata,
            client_capabilities=kwargs.pop("client_capabilities", self.client_capabilities),
            server_capabilities=kwargs.pop("server_capabilities", self.server_capabilities),
            roots=kwargs.pop("roots", self.roots),
            protocol_version=kwargs.pop("protocol_version", self.protocol_version),
            runtime=kwargs.pop("runtime", self.runtime),
            config={**self._config, **kwargs.pop("config", {})},
            vfs=kwargs.pop("vfs", self._vfs),
        )

    async def cleanup(self) -> None:
        preserved_paths: set[str] = set()
        if self.runtime is not None and hasattr(self.runtime, "artifacts"):
            await self.runtime.artifacts.cleanup_session(self.session_id)
            preserved_paths = self.runtime.artifacts.list_retained_paths(context_id=self.session_id)
        if self._vfs is not None or self.runtime is not None:
            await self.vfs.cleanup_context(self.session_id, preserve_paths=preserved_paths)
