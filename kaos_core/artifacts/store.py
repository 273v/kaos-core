from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

from kaos_core.artifacts.models import ArtifactManifest
from kaos_core.exceptions import ResourceError
from kaos_core.logging import get_logger
from kaos_core.protocol.roots import Root
from kaos_core.types.enums import ArtifactRetentionPolicy, ArtifactRole
from kaos_core.vfs.backends import DiskBackend
from kaos_core.vfs.core import VirtualFileSystem

logger = get_logger(__name__)


class ArtifactStore:
    def __init__(
        self,
        vfs: VirtualFileSystem,
        *,
        manifest_context_id: str = "__kaos_artifacts__",
        manifest_prefix: str = "manifests",
        max_inline_read_bytes: int = 262_144,
        default_chunk_size: int = 65_536,
        temporary_ttl_seconds: int = 3_600,
    ) -> None:
        self._vfs = vfs
        self._manifest_context_id = manifest_context_id
        self._manifest_prefix = self._vfs.normalize_path(manifest_prefix)
        self._max_inline_read_bytes = max_inline_read_bytes
        self._default_chunk_size = default_chunk_size
        self._temporary_ttl_seconds = temporary_ttl_seconds
        self._artifacts: dict[str, ArtifactManifest] = {}
        self._uri_index: dict[str, str] = {}
        self._load_persisted_manifests()

    def _manifest_record_path(self, artifact_id: str) -> str:
        if not self._manifest_prefix:
            return f"{artifact_id}.json"
        return self._vfs.safe_join(self._manifest_prefix, f"{artifact_id}.json")

    def _index_manifest(self, manifest: ArtifactManifest) -> ArtifactManifest:
        self._artifacts[manifest.artifact_id] = manifest
        self._uri_index[manifest.uri] = manifest.artifact_id
        self._uri_index[manifest.body_uri] = manifest.artifact_id
        self._uri_index[manifest.manifest_uri] = manifest.artifact_id
        return manifest

    def _drop_manifest(self, manifest: ArtifactManifest) -> None:
        self._artifacts.pop(manifest.artifact_id, None)
        self._uri_index.pop(manifest.uri, None)
        self._uri_index.pop(manifest.body_uri, None)
        self._uri_index.pop(manifest.manifest_uri, None)

    def _load_persisted_manifests(self) -> None:
        backend = self._vfs._backend()
        if not isinstance(backend, DiskBackend):
            return

        scoped_prefix = self._vfs._scope(self._manifest_prefix, self._manifest_context_id)
        manifest_dir = backend.resolve_path(scoped_prefix)
        if not manifest_dir.exists():
            return

        for record_path in sorted(manifest_dir.rglob("*.json")):
            try:
                manifest = ArtifactManifest.model_validate_json(
                    record_path.read_text(encoding="utf-8")
                )
            except Exception as exc:
                logger.warning(
                    "Skipping invalid persisted artifact manifest at %s: %s",
                    record_path,
                    exc,
                )
                continue
            self._index_manifest(manifest)

    async def _persist_manifest(self, manifest: ArtifactManifest) -> None:
        await self._vfs.write(
            self._manifest_record_path(manifest.artifact_id),
            manifest.model_dump_json(indent=2).encode("utf-8"),
            context_id=self._manifest_context_id,
        )

    async def _delete_manifest_record(self, artifact_id: str) -> None:
        await self._vfs.delete(
            self._manifest_record_path(artifact_id),
            context_id=self._manifest_context_id,
        )

    async def _restore_manifest(self, artifact_id: str) -> ArtifactManifest | None:
        if artifact_id in self._artifacts:
            return self._artifacts[artifact_id]
        try:
            payload = await self._vfs.read(
                self._manifest_record_path(artifact_id),
                context_id=self._manifest_context_id,
            )
        except Exception:
            return None
        try:
            manifest = ArtifactManifest.model_validate_json(payload)
        except Exception as exc:
            raise ResourceError(
                "Artifact manifest record is invalid", artifact_id=artifact_id
            ) from exc
        return self._index_manifest(manifest)

    def _artifact_id_from_identifier(self, uri_or_id: str) -> str:
        if uri_or_id.startswith("kaos://artifacts/"):
            return uri_or_id.removeprefix("kaos://artifacts/").split("/", 1)[0]
        return uri_or_id

    async def _resolve_async(self, uri_or_id: str) -> ArtifactManifest:
        if uri_or_id in self._artifacts:
            return self._artifacts[uri_or_id]
        if uri_or_id in self._uri_index:
            return self._artifacts[self._uri_index[uri_or_id]]

        artifact_id = self._artifact_id_from_identifier(uri_or_id)
        manifest = await self._restore_manifest(artifact_id)
        if manifest is None:
            details = {"artifact_id": artifact_id}
            if uri_or_id.startswith("kaos://artifacts/"):
                details = {"uri": uri_or_id}
            raise ResourceError("Unknown artifact", **details)
        return manifest

    def _root_path(self, root: Root) -> Path | None:
        parsed = urlparse(root.uri)
        if parsed.scheme != "file":
            return None
        return Path(unquote(parsed.path or "/")).resolve()

    def _assert_roots_allow(self, manifest: ArtifactManifest, roots: list[Root] | None) -> None:
        if not roots:
            return

        resolved_path = self._vfs.resolve_disk_path(manifest.path, context_id=manifest.context_id)
        if resolved_path is None:
            return

        root_paths = [
            root_path for root in roots if (root_path := self._root_path(root)) is not None
        ]
        if not root_paths:
            raise ResourceError(
                "Artifact access denied by roots policy",
                artifact_id=manifest.artifact_id,
                path=str(resolved_path),
            )

        for root_path in root_paths:
            try:
                resolved_path.relative_to(root_path)
            except ValueError:
                continue
            return

        raise ResourceError(
            "Artifact access denied by roots policy",
            artifact_id=manifest.artifact_id,
            path=str(resolved_path),
        )

    def _has_live_body_reference(self, manifest: ArtifactManifest) -> bool:
        return any(
            item.artifact_id != manifest.artifact_id
            and item.context_id == manifest.context_id
            and item.path == manifest.path
            for item in self._artifacts.values()
        )

    async def create_from_path(
        self,
        path: str,
        *,
        context_id: str,
        session_id: str,
        name: str,
        workflow_id: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
        role: ArtifactRole = ArtifactRole.BODY,
        provenance: dict[str, Any] | None = None,
        retention_policy: ArtifactRetentionPolicy | str | None = ArtifactRetentionPolicy.SESSION,
        metadata: dict[str, Any] | None = None,
        checksum: bool = False,
        ttl_seconds: int | None = None,
    ) -> ArtifactManifest:
        normalized_path = self._vfs.normalize_path(path)
        stat = await self._vfs.stat(normalized_path, context_id=context_id)
        if not stat.exists or stat.kind != "file":
            msg = f"Artifact path does not exist: {normalized_path}"
            raise FileNotFoundError(msg)

        resolved_policy = (
            ArtifactRetentionPolicy(retention_policy)
            if retention_policy is not None
            else ArtifactRetentionPolicy.SESSION
        )
        if ttl_seconds is not None and ttl_seconds <= 0:
            msg = "Artifact TTL must be positive"
            raise ValueError(msg)

        artifact_id = str(uuid4())
        checksum_value: str | None = None
        if checksum:
            checksum_value = sha256(
                await self._vfs.read(normalized_path, context_id=context_id)
            ).hexdigest()

        expires_at: str | None = None
        if resolved_policy is ArtifactRetentionPolicy.TEMPORARY:
            ttl = ttl_seconds or self._temporary_ttl_seconds
            expires_at = (datetime.now(tz=UTC) + timedelta(seconds=ttl)).isoformat()

        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            session_id=session_id,
            context_id=context_id,
            workflow_id=workflow_id,
            name=name,
            description=description,
            uri=f"kaos://artifacts/{artifact_id}",
            role=role,
            mime_type=mime_type or stat.mime_type,
            size=stat.size,
            checksum=checksum_value,
            created_at=stat.created_at,
            modified_at=stat.modified_at,
            path=normalized_path,
            provenance=provenance or {},
            retention_policy=resolved_policy,
            expires_at=expires_at,
            metadata=metadata or {},
        )
        self.register(manifest)
        await self._persist_manifest(manifest)
        return manifest

    def register(self, manifest: ArtifactManifest) -> ArtifactManifest:
        return self._index_manifest(manifest)

    async def refresh(self) -> None:
        self._artifacts.clear()
        self._uri_index.clear()
        self._load_persisted_manifests()

    def get(self, artifact_id: str) -> ArtifactManifest:
        try:
            return self._artifacts[artifact_id]
        except KeyError as exc:
            raise ResourceError("Unknown artifact", artifact_id=artifact_id) from exc

    def resolve(self, uri_or_id: str) -> ArtifactManifest:
        if uri_or_id in self._artifacts:
            return self._artifacts[uri_or_id]
        try:
            artifact_id = self._uri_index[uri_or_id]
        except KeyError as exc:
            details = {"artifact_id": uri_or_id}
            if uri_or_id.startswith("kaos://artifacts/"):
                details = {"uri": uri_or_id}
            raise ResourceError("Unknown artifact", **details) from exc
        return self.get(artifact_id)

    def list_artifacts(
        self,
        *,
        session_id: str | None = None,
        workflow_id: str | None = None,
        role: ArtifactRole | None = None,
    ) -> list[ArtifactManifest]:
        results = list(self._artifacts.values())
        if session_id is not None:
            results = [item for item in results if item.session_id == session_id]
        if workflow_id is not None:
            results = [item for item in results if item.workflow_id == workflow_id]
        if role is not None:
            results = [item for item in results if item.role is role]
        return sorted(results, key=lambda item: item.created_at or item.artifact_id)

    def list_retained_paths(self, *, context_id: str) -> set[str]:
        return {
            manifest.path
            for manifest in self._artifacts.values()
            if manifest.context_id == context_id
        }

    async def read_body(
        self,
        artifact_id: str,
        *,
        start: int = 0,
        length: int | None = None,
        roots: list[Root] | None = None,
        max_bytes: int | None = None,
    ) -> bytes:
        manifest = await self._resolve_async(artifact_id)
        self._assert_roots_allow(manifest, roots)

        if start < 0:
            raise ResourceError("Artifact read start must be non-negative", artifact_id=artifact_id)
        if length is not None and length <= 0:
            raise ResourceError("Artifact read length must be positive", artifact_id=artifact_id)
        if start == 0 and length is None and max_bytes is not None and manifest.size > max_bytes:
            raise ResourceError(
                "Artifact exceeds inline read limit",
                artifact_id=artifact_id,
                size=manifest.size,
                max_bytes=max_bytes,
                chunk_uri=manifest.chunk_uri(0),
            )

        stat = await self._vfs.stat(manifest.path, context_id=manifest.context_id)
        if not stat.exists or stat.kind != "file":
            raise ResourceError(
                "Artifact backing file is missing",
                artifact_id=artifact_id,
                path=manifest.path,
            )
        return await self._vfs.read_range(
            manifest.path,
            start=start,
            length=length,
            context_id=manifest.context_id,
        )

    async def read_chunk(
        self,
        artifact_id: str,
        *,
        chunk_index: int,
        chunk_size: int | None = None,
        roots: list[Root] | None = None,
    ) -> bytes:
        manifest = await self._resolve_async(artifact_id)
        resolved_chunk_size = chunk_size or self._default_chunk_size
        if chunk_index < 0:
            raise ResourceError(
                "Artifact chunk index must be non-negative", artifact_id=artifact_id
            )
        if resolved_chunk_size <= 0:
            raise ResourceError("Artifact chunk size must be positive", artifact_id=artifact_id)

        start = chunk_index * resolved_chunk_size
        if start >= manifest.size:
            raise ResourceError(
                "Artifact chunk is out of range",
                artifact_id=artifact_id,
                chunk_index=chunk_index,
            )
        return await self.read_body(
            manifest.artifact_id,
            start=start,
            length=resolved_chunk_size,
            roots=roots,
            max_bytes=resolved_chunk_size,
        )

    async def read_text(self, artifact_id: str, *, encoding: str = "utf-8") -> str:
        return (await self.read_body(artifact_id, max_bytes=None)).decode(encoding)

    async def read_uri(self, uri: str, *, roots: list[Root] | None = None) -> str | bytes:
        manifest = await self._resolve_async(uri)
        self._assert_roots_allow(manifest, roots)
        if uri.endswith("/manifest"):
            return json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True)
        payload = await self.read_body(
            manifest.artifact_id,
            roots=roots,
            max_bytes=self._max_inline_read_bytes,
        )
        if manifest.mime_type and (
            manifest.mime_type.startswith("text/")
            or manifest.mime_type in {"application/json", "application/xml"}
        ):
            return payload.decode("utf-8", errors="replace")
        return payload

    async def delete(self, artifact_id: str, *, delete_body: bool = True) -> ArtifactManifest:
        manifest = await self._resolve_async(artifact_id)
        self._drop_manifest(manifest)
        await self._delete_manifest_record(manifest.artifact_id)

        if delete_body and not self._has_live_body_reference(manifest):
            await self._vfs.delete(manifest.path, context_id=manifest.context_id)
        return manifest

    async def cleanup_session(self, session_id: str) -> int:
        deleted = 0
        for manifest in list(self.list_artifacts(session_id=session_id)):
            if manifest.retention_policy is ArtifactRetentionPolicy.PERSISTENT:
                continue
            await self.delete(manifest.artifact_id)
            deleted += 1
        return deleted

    async def cleanup_expired(self, *, now: datetime | None = None) -> int:
        deleted = 0
        current_time = now or datetime.now(tz=UTC)
        for manifest in list(self._artifacts.values()):
            if manifest.retention_policy is not ArtifactRetentionPolicy.TEMPORARY:
                continue
            if not manifest.is_expired(now=current_time):
                continue
            await self.delete(manifest.artifact_id)
            deleted += 1
        return deleted
