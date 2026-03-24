from __future__ import annotations

from pathlib import Path

from pydantic import Field

from kaos_core.types.content import KaosModel
from kaos_core.types.enums import IsolationMode, StorageBackend


class VFSConfig(KaosModel):
    default_backend: StorageBackend = StorageBackend.DISK
    max_memory_size: int = Field(default=10_000_000, ge=0)
    disk_base_path: Path = Path(".kaos-vfs")
    enable_compression: bool = False
    lazy_compression: bool = True
    isolation_mode: IsolationMode = IsolationMode.CONTEXT
    auto_cleanup: bool = True
    cache_ttl: float = Field(default=300.0, ge=0.0)


class VFSMetadata(KaosModel):
    path: str
    exists: bool = False
    kind: str = "missing"
    size: int = 0
    backend: StorageBackend
    context_id: str | None = None
    created_at: str | None = None
    modified_at: str | None = None
    accessed_at: str | None = None
    is_readable: bool | None = None
    is_writable: bool | None = None
    is_executable: bool | None = None
    mime_type: str | None = None


class VFSListPage(KaosModel):
    items: list[str] = Field(default_factory=list)
    next_cursor: str | None = None


class VFSWalkOptions(KaosModel):
    max_depth: int | None = Field(default=None, ge=0)
    include_hidden: bool = False
    include_directories: bool = False
    min_size: int | None = Field(default=None, ge=0)
    max_size: int | None = Field(default=None, ge=0)
    patterns: list[str] = Field(default_factory=list)


class VFSWalkEntry(KaosModel):
    path: str
    metadata: VFSMetadata
    error: str | None = None


class VFSWalkResult(KaosModel):
    items: list[VFSWalkEntry] = Field(default_factory=list)
    total_count: int = 0
    error_count: int = 0
