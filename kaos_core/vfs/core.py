from __future__ import annotations

import builtins
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from kaos_core.types.enums import IsolationMode, StorageBackend
from kaos_core.vfs.backends import DiskBackend, MemoryBackend, S3Backend, _normalize_relative_path
from kaos_core.vfs.models import (
    VFSConfig,
    VFSListPage,
    VFSMetadata,
    VFSWalkEntry,
    VFSWalkOptions,
    VFSWalkResult,
)

if TYPE_CHECKING:
    from kaos_core.vfs.path import VFSPath


class _BackendProtocol(Protocol):
    async def read(self, path: str) -> bytes: ...
    async def read_range(self, path: str, start: int = 0, length: int | None = None) -> bytes: ...
    async def write(self, path: str, data: bytes) -> int: ...
    async def delete(self, path: str) -> None: ...
    async def exists(self, path: str) -> bool: ...
    async def stat(self, path: str, context_id: str | None = None) -> VFSMetadata: ...
    async def list(self, prefix: str) -> builtins.list[str]: ...


class VirtualFileSystem:
    def __init__(self, config: VFSConfig | None = None) -> None:
        self.config = config or VFSConfig()
        self._memory = MemoryBackend()
        self._disk = DiskBackend(self.config.disk_base_path)
        self._s3: S3Backend | None = None  # Lazy — instantiated only if S3 backend is used

    def _disk_backend(self) -> DiskBackend:
        configured_base_path = self.config.disk_base_path.resolve()
        if self._disk.base_path != configured_base_path:
            self._disk = DiskBackend(self.config.disk_base_path)
        return self._disk

    def get_path(self, path: str, context_id: str | None = None) -> VFSPath:
        from kaos_core.vfs.path import VFSPath

        return VFSPath(self, self.normalize_path(path), context_id=context_id)

    def normalize_path(self, path: str) -> str:
        return _normalize_relative_path(path)

    def safe_join(self, base_path: str, *parts: str) -> str:
        joined = "/".join([base_path, *parts])
        normalized = self.normalize_path(joined)
        base = self.normalize_path(base_path)
        if base and normalized != base and not normalized.startswith(f"{base}/"):
            msg = f"Resolved path escapes base path: {base_path}"
            raise ValueError(msg)
        return normalized

    def _scope(self, path: str, context_id: str | None = None) -> str:
        normalized = self.normalize_path(path)
        if self.config.isolation_mode is IsolationMode.GLOBAL:
            return normalized
        if self.config.isolation_mode is IsolationMode.NAMESPACE:
            namespace = (context_id or "default").split(":", 1)[0]
            return f"{namespace}/{normalized}" if normalized else namespace
        context_prefix = context_id or "default"
        return f"{context_prefix}/{normalized}" if normalized else context_prefix

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
            return self._disk_backend()
        if self.config.default_backend is StorageBackend.S3:
            # Lazy instantiation — raises NotImplementedError with guidance
            if self._s3 is None:
                self._s3 = S3Backend()
            return self._s3
        return self._memory

    def resolve_disk_path(self, path: str, context_id: str | None = None) -> Path | None:
        backend = self._backend()
        if not isinstance(backend, DiskBackend):
            return None
        return backend.resolve_path(self._scope(path, context_id))

    async def read(self, path: str, context_id: str | None = None) -> bytes:
        return await self._backend().read(self._scope(path, context_id))

    async def read_range(
        self,
        path: str,
        start: int = 0,
        length: int | None = None,
        context_id: str | None = None,
    ) -> bytes:
        return await self._backend().read_range(self._scope(path, context_id), start, length)

    async def write(self, path: str, data: bytes, context_id: str | None = None) -> int:
        return await self._backend().write(self._scope(path, context_id), data)

    async def exists(self, path: str, context_id: str | None = None) -> bool:
        return await self._backend().exists(self._scope(path, context_id))

    async def stat(self, path: str, context_id: str | None = None) -> VFSMetadata:
        metadata = await self._backend().stat(self._scope(path, context_id), context_id=context_id)
        return metadata.model_copy(update={"path": self._strip_scope(metadata.path, context_id)})

    async def delete(self, path: str, context_id: str | None = None) -> None:
        await self._backend().delete(self._scope(path, context_id))

    async def list(self, prefix: str = "", context_id: str | None = None) -> builtins.list[str]:
        scoped_prefix = self._scope(prefix, context_id)
        if not prefix and self.config.isolation_mode is not IsolationMode.GLOBAL:
            scoped_prefix = self._scope_prefix(context_id)
        return await self._backend().list(scoped_prefix)

    async def list_page(
        self,
        prefix: str = "",
        *,
        context_id: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> VFSListPage:
        limit = max(1, limit)
        items = [
            self._strip_scope(item, context_id) for item in await self.list(prefix, context_id)
        ]
        start = int(cursor or "0")
        page_items = items[start : start + limit]
        next_cursor = str(start + limit) if start + limit < len(items) else None
        return VFSListPage(items=page_items, next_cursor=next_cursor)

    async def walk(
        self,
        prefix: str = "",
        *,
        context_id: str | None = None,
        options: VFSWalkOptions | None = None,
    ) -> VFSWalkResult:
        options = options or VFSWalkOptions()
        entries: list[VFSWalkEntry] = []
        errors = 0
        scoped_prefix = self.normalize_path(prefix)

        for path in [
            self._strip_scope(item, context_id) for item in await self.list(prefix, context_id)
        ]:
            relative = path.removeprefix(f"{scoped_prefix}/") if scoped_prefix else path
            depth = len([part for part in relative.split("/") if part])
            if options.max_depth is not None and depth > options.max_depth:
                continue
            if not options.include_hidden and any(
                part.startswith(".") for part in relative.split("/")
            ):
                continue
            if options.patterns and not any(fnmatch(path, pattern) for pattern in options.patterns):
                continue

            try:
                metadata = await self.stat(path, context_id=context_id)
            except Exception as exc:
                errors += 1
                entries.append(
                    VFSWalkEntry(
                        path=path,
                        metadata=VFSMetadata(path=path, backend=self.config.default_backend),
                        error=str(exc),
                    )
                )
                continue

            if metadata.kind == "directory" and not options.include_directories:
                continue
            if options.min_size is not None and metadata.size < options.min_size:
                continue
            if options.max_size is not None and metadata.size > options.max_size:
                continue
            entries.append(VFSWalkEntry(path=path, metadata=metadata))

        return VFSWalkResult(items=entries, total_count=len(entries), error_count=errors)

    async def probe_text(
        self,
        path: str,
        *,
        context_id: str | None = None,
        max_bytes: int = 512,
        encoding: str = "utf-8",
    ) -> dict[str, object]:
        chunk = await self.read_range(path, start=0, length=max_bytes, context_id=context_id)
        metadata = await self.stat(path, context_id=context_id)
        text = chunk.decode(encoding, errors="replace")
        return {
            "path": self.normalize_path(path),
            "preview": text,
            "truncated": metadata.size > len(chunk),
            "size": metadata.size,
            "mime_type": metadata.mime_type,
        }

    async def cleanup_context(
        self,
        context_id: str,
        *,
        preserve_paths: set[str] | None = None,
    ) -> None:
        preserved = {self.normalize_path(path) for path in preserve_paths or set()}
        for path in await self.list("", context_id=context_id):
            if self._strip_scope(path, context_id) in preserved:
                continue
            await self._backend().delete(path)
