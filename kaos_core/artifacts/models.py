from __future__ import annotations

from typing import Any

from pydantic import Field

from kaos_core.types.content import KaosModel
from kaos_core.types.enums import ArtifactRole


class ArtifactRef(KaosModel):
    artifact_id: str
    uri: str
    role: ArtifactRole
    mime_type: str | None = None
    size: int = 0
    path: str


class ArtifactManifest(KaosModel):
    artifact_id: str
    session_id: str
    context_id: str
    workflow_id: str | None = None
    name: str
    description: str | None = None
    uri: str
    role: ArtifactRole
    mime_type: str | None = None
    size: int = 0
    checksum: str | None = None
    created_at: str | None = None
    modified_at: str | None = None
    path: str
    provenance: dict[str, Any] = Field(default_factory=dict)
    retention_policy: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def manifest_uri(self) -> str:
        return f"kaos://artifacts/{self.artifact_id}/manifest"

    @property
    def body_uri(self) -> str:
        return f"kaos://artifacts/{self.artifact_id}/body"

    def to_ref(self) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=self.artifact_id,
            uri=self.body_uri,
            role=self.role,
            mime_type=self.mime_type,
            size=self.size,
            path=self.path,
        )
