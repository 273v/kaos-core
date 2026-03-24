from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, Protocol

from kaos_core.types.enums import IsolationMode, StorageBackend
from kaos_core.vfs.backends import DiskBackend, MemoryBackend, S3Backend
from kaos_core.vfs.models import VFSConfig

if TYPE_CHECKING:
    from kaos_core.vfs.path import VFSPath


class _BackendProtocol(Protocol):
    async def read(self, path: str) -> bytes: ...
    async def write(self, path: str, data: bytes) -> int: ...
    async def delete(self, path: str) -> None: ...
    async def exists(self, path: str) -> bool: ...
    async def list(self, prefix: str) -> builtins.list[str]: ...


class VirtualFileSystem:
    def __init__(self, config: VFSConfig | None = None) -> None:
        self.config = config or VFSConfig()
        self._memory = MemoryBackend()
        self._disk = DiskBackend(self.config.disk_base_path)
        self._s3 = S3Backend()

    def get_path(self, path: str, context_id: str | None = None) -> VFSPath:
        from kaos_core.vfs.path import VFSPath

        return VFSPath(self, path, context_id=context_id)

    def _scope(self, path: str, context_id: str | None = None) -> str:
        if self.config.isolation_mode is IsolationMode.GLOBAL:
            return path
        if self.config.isolation_mode is IsolationMode.NAMESPACE:
            namespace = (context_id or "default").split(":", 1)[0]
            return f"{namespace}/{path.lstrip('/')}"
        return f"{(context_id or 'default')}/{path.lstrip('/')}"

    def _scope_prefix(self, context_id: str | None = None) -> str:
        if self.config.isolation_mode is IsolationMode.GLOBAL:
            return ""
        if self.config.isolation_mode is IsolationMode.NAMESPACE:
            namespace = (context_id or "default").split(":", 1)[0]
            return f"{namespace}/"
        return f"{(context_id or 'default')}/"

    def _strip_scope(self, path: str, context_id: str | None = None) -> str:
        prefix = self._scope_prefix(context_id)
        if prefix and path.startswith(prefix):
            return path[len(prefix) :]
        return path.lstrip("/")

    def _backend(self) -> _BackendProtocol:
        if self.config.default_backend is StorageBackend.DISK:
            return self._disk
        if self.config.default_backend is StorageBackend.S3:
            return self._s3
        return self._memory

    async def read(self, path: str, context_id: str | None = None) -> bytes:
        return await self._backend().read(self._scope(path, context_id))

    async def write(self, path: str, data: bytes, context_id: str | None = None) -> int:
        return await self._backend().write(self._scope(path, context_id), data)

    async def exists(self, path: str, context_id: str | None = None) -> bool:
        return await self._backend().exists(self._scope(path, context_id))

    async def delete(self, path: str, context_id: str | None = None) -> None:
        await self._backend().delete(self._scope(path, context_id))

    async def list(self, prefix: str = "", context_id: str | None = None) -> builtins.list[str]:
        return await self._backend().list(self._scope(prefix, context_id))

    async def cleanup_context(self, context_id: str) -> None:
        for path in await self.list("", context_id=context_id):
            await self._backend().delete(path)
