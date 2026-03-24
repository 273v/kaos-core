from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kaos_core.vfs.core import VirtualFileSystem


class VFSPath:
    def __init__(self, vfs: VirtualFileSystem, path: str, *, context_id: str | None = None) -> None:
        self.vfs = vfs
        self._path = PurePosixPath(path)
        self.context_id = context_id

    def __fspath__(self) -> str:
        return str(self._path)

    def __truediv__(self, other: str) -> VFSPath:
        return VFSPath(self.vfs, str(self._path / other), context_id=self.context_id)

    @property
    def name(self) -> str:
        return self._path.name

    @property
    def parent(self) -> VFSPath:
        return VFSPath(self.vfs, str(self._path.parent), context_id=self.context_id)

    @property
    def parts(self) -> tuple[str, ...]:
        return self._path.parts

    async def exists(self) -> bool:
        return await self.vfs.exists(str(self._path), context_id=self.context_id)

    async def is_file(self) -> bool:
        return await self.exists()

    async def is_dir(self) -> bool:
        prefix = str(self._path).rstrip("/") + "/"
        return bool(await self.vfs.list(prefix, context_id=self.context_id))

    async def read_bytes(self) -> bytes:
        return await self.vfs.read(str(self._path), context_id=self.context_id)

    async def read_text(self, encoding: str = "utf-8") -> str:
        return (await self.read_bytes()).decode(encoding)

    async def write_bytes(self, data: bytes) -> int:
        return await self.vfs.write(str(self._path), data, context_id=self.context_id)

    async def write_text(self, text: str, encoding: str = "utf-8") -> int:
        return await self.write_bytes(text.encode(encoding))

    async def iterdir(self) -> list[VFSPath]:
        prefix = str(self._path).rstrip("/") + "/"
        return [
            VFSPath(
                self.vfs,
                self.vfs._strip_scope(entry, self.context_id),
                context_id=self.context_id,
            )
            for entry in await self.vfs.list(prefix, context_id=self.context_id)
        ]

    async def mkdir(self) -> None:
        return None

    async def unlink(self) -> None:
        await self.vfs.delete(str(self._path), context_id=self.context_id)

    async def rmdir(self) -> None:
        for child in await self.iterdir():
            await child.unlink()
