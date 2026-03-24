from __future__ import annotations

import json
from hashlib import sha256
from typing import Any
from uuid import uuid4

from kaos_core.artifacts.models import ArtifactManifest
from kaos_core.types.enums import ArtifactRole
from kaos_core.vfs.core import VirtualFileSystem


class ArtifactStore:
    def __init__(self, vfs: VirtualFileSystem) -> None:
        self._vfs = vfs
        self._artifacts: dict[str, ArtifactManifest] = {}
        self._uri_index: dict[str, str] = {}

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
        retention_policy: str | None = "session",
        metadata: dict[str, Any] | None = None,
        checksum: bool = False,
    ) -> ArtifactManifest:
        normalized_path = self._vfs.normalize_path(path)
        stat = await self._vfs.stat(normalized_path, context_id=context_id)
        if not stat.exists or stat.kind != "file":
            msg = f"Artifact path does not exist: {normalized_path}"
            raise FileNotFoundError(msg)

        artifact_id = str(uuid4())
        checksum_value: str | None = None
        if checksum:
            checksum_value = sha256(
                await self._vfs.read(normalized_path, context_id=context_id)
            ).hexdigest()

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
            retention_policy=retention_policy,
            metadata=metadata or {},
        )
        self.register(manifest)
        return manifest

    def register(self, manifest: ArtifactManifest) -> ArtifactManifest:
        self._artifacts[manifest.artifact_id] = manifest
        self._uri_index[manifest.uri] = manifest.artifact_id
        self._uri_index[manifest.body_uri] = manifest.artifact_id
        self._uri_index[manifest.manifest_uri] = manifest.artifact_id
        return manifest

    def get(self, artifact_id: str) -> ArtifactManifest:
        return self._artifacts[artifact_id]

    def resolve(self, uri_or_id: str) -> ArtifactManifest:
        if uri_or_id in self._artifacts:
            return self._artifacts[uri_or_id]
        artifact_id = self._uri_index[uri_or_id]
        return self._artifacts[artifact_id]

    def list(
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

    async def read_body(
        self, artifact_id: str, *, start: int = 0, length: int | None = None
    ) -> bytes:
        manifest = self.get(artifact_id)
        return await self._vfs.read_range(
            manifest.path,
            start=start,
            length=length,
            context_id=manifest.context_id,
        )

    async def read_text(self, artifact_id: str, *, encoding: str = "utf-8") -> str:
        return (await self.read_body(artifact_id)).decode(encoding)

    async def read_uri(self, uri: str) -> str | bytes:
        manifest = self.resolve(uri)
        if uri.endswith("/manifest"):
            return json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True)
        payload = await self.read_body(manifest.artifact_id)
        if manifest.mime_type and (
            manifest.mime_type.startswith("text/")
            or manifest.mime_type in {"application/json", "application/xml"}
        ):
            return payload.decode("utf-8", errors="replace")
        return payload
