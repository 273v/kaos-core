from __future__ import annotations

import asyncio
import builtins
from pathlib import Path


class MemoryBackend:
    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}

    async def read(self, path: str) -> bytes:
        return self._files[path]

    async def write(self, path: str, data: bytes) -> int:
        self._files[path] = data
        return len(data)

    async def delete(self, path: str) -> None:
        self._files.pop(path, None)

    async def exists(self, path: str) -> bool:
        return path in self._files

    async def list(self, prefix: str) -> builtins.list[str]:
        return sorted(name for name in self._files if name.startswith(prefix))


class DiskBackend:
    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        target = self.base_path / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    async def read(self, path: str) -> bytes:
        return await asyncio.to_thread(self._resolve(path).read_bytes)

    async def write(self, path: str, data: bytes) -> int:
        target = self._resolve(path)
        await asyncio.to_thread(target.write_bytes, data)
        return len(data)

    async def delete(self, path: str) -> None:
        target = self._resolve(path)
        if target.exists():
            await asyncio.to_thread(target.unlink)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._resolve(path).exists)

    async def list(self, prefix: str) -> builtins.list[str]:
        root = self._resolve(prefix)
        if root.is_file():
            return [prefix]
        if not root.exists():
            return []
        return await asyncio.to_thread(
            lambda: sorted(
                str(child.relative_to(self.base_path))
                for child in root.rglob("*")
                if child.is_file()
            )
        )


class S3Backend:
    async def read(self, path: str) -> bytes:
        raise NotImplementedError("S3 backend is a stub in v0.1")

    async def write(self, path: str, data: bytes) -> int:
        raise NotImplementedError("S3 backend is a stub in v0.1")

    async def delete(self, path: str) -> None:
        raise NotImplementedError("S3 backend is a stub in v0.1")

    async def exists(self, path: str) -> bool:
        raise NotImplementedError("S3 backend is a stub in v0.1")

    async def list(self, prefix: str) -> builtins.list[str]:
        raise NotImplementedError("S3 backend is a stub in v0.1")
