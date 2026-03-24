from __future__ import annotations

from pathlib import Path

from pydantic import Field

from kaos_core.types.content import KaosModel
from kaos_core.types.enums import IsolationMode, StorageBackend


class VFSConfig(KaosModel):
    default_backend: StorageBackend = StorageBackend.MEMORY
    max_memory_size: int = Field(default=10_000_000, ge=0)
    disk_base_path: Path = Path(".kaos-vfs")
    enable_compression: bool = False
    lazy_compression: bool = True
    isolation_mode: IsolationMode = IsolationMode.CONTEXT
    auto_cleanup: bool = True
    cache_ttl: float = Field(default=300.0, ge=0.0)


class VFSMetadata(KaosModel):
    path: str
    size: int = 0
    backend: StorageBackend
    context_id: str | None = None
