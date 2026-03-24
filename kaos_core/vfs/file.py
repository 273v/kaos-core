from __future__ import annotations

import io
from collections.abc import Buffer


class VFSFile(io.RawIOBase):
    def __init__(self, initial_bytes: bytes | None = None) -> None:
        super().__init__()
        self._buffer = io.BytesIO(initial_bytes or b"")

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    def write(self, b: Buffer) -> int:
        return self._buffer.write(bytes(b))

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self._buffer.seek(offset, whence)

    def tell(self) -> int:
        return self._buffer.tell()

    def close(self) -> None:
        self._buffer.close()
        super().close()
