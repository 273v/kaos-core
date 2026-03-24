from __future__ import annotations

import asyncio
import builtins
import mimetypes
import os
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from kaos_core.types.enums import StorageBackend
from kaos_core.vfs.models import VFSMetadata


def _normalize_relative_path(path: str) -> str:
    pure = PurePosixPath("/" + path.lstrip("/"))
    parts = [part for part in pure.parts if part not in {"/", ".", ""}]
    if any(part == ".." for part in parts):
        msg = f"Path escapes VFS root: {path}"
        raise ValueError(msg)
    return str(PurePosixPath(*parts)) if parts else ""


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat()


def _build_metadata(
    *,
    path: str,
    backend: StorageBackend,
    context_id: str | None,
    exists: bool,
    kind: str,
    size: int = 0,
    created_at: str | None = None,
    modified_at: str | None = None,
    accessed_at: str | None = None,
    is_readable: bool | None = None,
    is_writable: bool | None = None,
    is_executable: bool | None = None,
) -> VFSMetadata:
    return VFSMetadata(
        path=path,
        exists=exists,
        kind=kind,
        size=size,
        backend=backend,
        context_id=context_id,
        created_at=created_at,
        modified_at=modified_at,
        accessed_at=accessed_at,
        is_readable=is_readable,
        is_writable=is_writable,
        is_executable=is_executable,
        mime_type=mimetypes.guess_type(path)[0],
    )


class MemoryBackend:
    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}

    async def read(self, path: str) -> bytes:
        return self._files[path]

    async def read_range(self, path: str, start: int = 0, length: int | None = None) -> bytes:
        data = await self.read(path)
        end = None if length is None else start + length
        return data[start:end]

    async def write(self, path: str, data: bytes) -> int:
        self._files[path] = data
        return len(data)

    async def delete(self, path: str) -> None:
        self._files.pop(path, None)

    async def exists(self, path: str) -> bool:
        return path in self._files

    async def stat(self, path: str, context_id: str | None = None) -> VFSMetadata:
        normalized = _normalize_relative_path(path)
        if normalized in self._files:
            data = self._files[normalized]
            return _build_metadata(
                path=normalized,
                backend=StorageBackend.MEMORY,
                context_id=context_id,
                exists=True,
                kind="file",
                size=len(data),
                is_readable=True,
                is_writable=True,
                is_executable=False,
            )

        directory_prefix = f"{normalized}/" if normalized else ""
        if any(name.startswith(directory_prefix) for name in self._files):
            return _build_metadata(
                path=normalized,
                backend=StorageBackend.MEMORY,
                context_id=context_id,
                exists=True,
                kind="directory",
                is_readable=True,
                is_writable=True,
                is_executable=True,
            )

        return _build_metadata(
            path=normalized,
            backend=StorageBackend.MEMORY,
            context_id=context_id,
            exists=False,
            kind="missing",
        )

    async def list(self, prefix: str) -> builtins.list[str]:
        normalized = _normalize_relative_path(prefix)
        return sorted(
            name
            for name in self._files
            if not normalized or name == normalized or name.startswith(f"{normalized}/")
        )


class DiskBackend:
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path.resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str, *, create_parents: bool = False) -> Path:
        normalized = _normalize_relative_path(path)
        candidate = (self.base_path / normalized).resolve()
        candidate.relative_to(self.base_path)
        if create_parents:
            parent = candidate.parent if normalized else candidate
            parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def resolve_path(self, path: str, *, create_parents: bool = False) -> Path:
        return self._resolve(path, create_parents=create_parents)

    async def read(self, path: str) -> bytes:
        return await asyncio.to_thread(self._resolve(path).read_bytes)

    async def read_range(self, path: str, start: int = 0, length: int | None = None) -> bytes:
        data = await self.read(path)
        end = None if length is None else start + length
        return data[start:end]

    async def write(self, path: str, data: bytes) -> int:
        target = self._resolve(path, create_parents=True)
        await asyncio.to_thread(target.write_bytes, data)
        return len(data)

    async def delete(self, path: str) -> None:
        target = self._resolve(path)
        if await asyncio.to_thread(target.exists):
            await asyncio.to_thread(target.unlink)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._resolve(path).exists)

    async def stat(self, path: str, context_id: str | None = None) -> VFSMetadata:
        normalized = _normalize_relative_path(path)
        target = self._resolve(path)
        if not await asyncio.to_thread(target.exists):
            return _build_metadata(
                path=normalized,
                backend=StorageBackend.DISK,
                context_id=context_id,
                exists=False,
                kind="missing",
            )

        stat_result = await asyncio.to_thread(target.stat)
        return _build_metadata(
            path=normalized,
            backend=StorageBackend.DISK,
            context_id=context_id,
            exists=True,
            kind="directory" if target.is_dir() else "file",
            size=0 if target.is_dir() else stat_result.st_size,
            created_at=_timestamp(stat_result.st_ctime),
            modified_at=_timestamp(stat_result.st_mtime),
            accessed_at=_timestamp(stat_result.st_atime),
            is_readable=os.access(target, os.R_OK),
            is_writable=os.access(target, os.W_OK),
            is_executable=os.access(target, os.X_OK),
        )

    async def list(self, prefix: str) -> builtins.list[str]:
        normalized = _normalize_relative_path(prefix)

        def _list_files() -> builtins.list[str]:
            return sorted(
                str(child.relative_to(self.base_path))
                for child in self.base_path.rglob("*")
                if child.is_file()
                and (
                    not normalized
                    or str(child.relative_to(self.base_path)) == normalized
                    or str(child.relative_to(self.base_path)).startswith(f"{normalized}/")
                )
            )

        return await asyncio.to_thread(_list_files)


class S3Backend:
    async def read(self, path: str) -> bytes:
        raise NotImplementedError("S3 backend is a stub in v0.1")

    async def read_range(self, path: str, start: int = 0, length: int | None = None) -> bytes:
        del start, length
        raise NotImplementedError("S3 backend is a stub in v0.1")

    async def write(self, path: str, data: bytes) -> int:
        raise NotImplementedError("S3 backend is a stub in v0.1")

    async def delete(self, path: str) -> None:
        raise NotImplementedError("S3 backend is a stub in v0.1")

    async def exists(self, path: str) -> bool:
        raise NotImplementedError("S3 backend is a stub in v0.1")

    async def stat(self, path: str, context_id: str | None = None) -> VFSMetadata:
        del path, context_id
        raise NotImplementedError("S3 backend is a stub in v0.1")

    async def list(self, prefix: str) -> builtins.list[str]:
        raise NotImplementedError("S3 backend is a stub in v0.1")
