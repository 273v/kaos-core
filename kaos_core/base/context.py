from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import uuid4

from kaos_core.exceptions import RegistryError
from kaos_core.logging import get_logger
from kaos_core.protocol.capabilities import ClientCapabilities
from kaos_core.protocol.initialize import InitializeRequest, InitializeResult
from kaos_core.protocol.roots import Root

ProgressCallback = Callable[[float, float | None, str | None], Awaitable[None] | None]

_T = TypeVar("_T")


def _normalize_default_namespace(namespace: str) -> str:
    """Normalize a default VFS namespace string.

    - Empty / None / whitespace -> "".
    - Strips leading "/" so callers can pass either "files/" or "/files/".
    - Ensures trailing "/" so prepending is a plain string concat.
    """
    if not namespace:
        return ""
    cleaned = namespace.strip().lstrip("/")
    if not cleaned:
        return ""
    if not cleaned.endswith("/"):
        cleaned = cleaned + "/"
    return cleaned


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
        default_vfs_namespace: str = "",
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
        self.default_vfs_namespace = _normalize_default_namespace(default_vfs_namespace)
        self._progress_callback: ProgressCallback | None = None
        self._logger = get_logger("kaos.context")

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
        self._logger.info(message, extra=self._log_extra(kwargs))

    def warning(self, message: str, **kwargs: Any) -> None:
        self._logger.warning(message, extra=self._log_extra(kwargs))

    def error(self, message: str, **kwargs: Any) -> None:
        self._logger.error(message, extra=self._log_extra(kwargs))

    def _log_extra(self, extra: dict[str, Any]) -> dict[str, Any]:
        merged = dict(extra)
        merged["session_id"] = self.session_id
        merged["trace_id"] = self.trace_id or "-"
        return merged

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

    def get_module_settings(self, cls: type[_T]) -> _T:
        """Get typed module settings, overlaying context config overrides.

        Calls ``cls.from_context(self)`` to merge environment defaults with
        any context-level overrides in ``_config``.

        Args:
            cls: A ``ModuleSettings`` subclass.

        Returns:
            A settings instance with context overrides applied.
        """
        return cls.from_context(self)  # ty: ignore[unresolved-attribute]

    async def read_resource(self, uri: str) -> Any:
        if self.runtime is None:
            msg = "Context is not attached to a runtime"
            raise RuntimeError(msg)
        try:
            return await self.runtime.resources.get_resource(uri, context=self)
        except RegistryError:
            if hasattr(self.runtime, "artifacts"):
                # Pass the caller session_id so the artifact-store fallback
                # cannot be used as a side-channel to read another
                # session's artifacts via the resource API.
                return await self.runtime.artifacts.read_uri(
                    uri,
                    roots=self.roots,
                    caller_session_id=self.session_id,
                )
            raise

    def get_vfs_path(self, path: str) -> Any:
        return self.vfs.get_path(path, context_id=self.session_id)

    def with_default_namespace(self, namespace: str) -> KaosContext:
        """Return a child context with a different default VFS namespace.

        Used by hosts (e.g. the kaos-ui single-user-chat backend) to declare
        that bare-name file inputs from agents should be looked up inside a
        well-known sub-prefix (e.g. ``"files/"``) of the session VFS.
        Resolver / vfs-list honor this when the caller does not supply an
        explicit scheme (``file://``, ``kaos://``, ``vfs://``).
        """
        return self.create_child_context(default_vfs_namespace=namespace)

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
            default_vfs_namespace=kwargs.pop("default_vfs_namespace", self.default_vfs_namespace),
        )

    async def cleanup(self) -> None:
        preserved_paths: set[str] = set()
        if self.runtime is not None and hasattr(self.runtime, "artifacts"):
            await self.runtime.artifacts.cleanup_session(self.session_id)
            preserved_paths = self.runtime.artifacts.list_retained_paths(context_id=self.session_id)
        if self._vfs is not None or self.runtime is not None:
            await self.vfs.cleanup_context(self.session_id, preserve_paths=preserved_paths)
