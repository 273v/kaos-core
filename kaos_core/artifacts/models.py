from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import Field

from kaos_core.types.content import KaosModel, ResourceLinkContent
from kaos_core.types.enums import ArtifactRetentionPolicy, ArtifactRole

if TYPE_CHECKING:
    from kaos_core.types.results import ToolResult

# ---------------------------------------------------------------------------
# Inline threshold constants (bytes)
# ---------------------------------------------------------------------------
INLINE_THRESHOLD = 16_384  # 16 KB — below this, inline content is fine
SUMMARY_THRESHOLD = 262_144  # 256 KB — above this, handle-only (no body inline)


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
    retention_policy: ArtifactRetentionPolicy | None = ArtifactRetentionPolicy.SESSION
    expires_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def manifest_uri(self) -> str:
        return f"kaos://artifacts/{self.artifact_id}/manifest"

    @property
    def body_uri(self) -> str:
        return f"kaos://artifacts/{self.artifact_id}/body"

    def chunk_uri(self, chunk_index: int) -> str:
        return f"kaos://artifacts/{self.artifact_id}/chunk/{chunk_index}"

    def range_uri(self, start: int, length: int) -> str:
        return f"kaos://artifacts/{self.artifact_id}/range/{start}/{length}"

    def is_expired(self, *, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        current_time = now or datetime.now(tz=UTC)
        return datetime.fromisoformat(self.expires_at) <= current_time

    def to_ref(self) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=self.artifact_id,
            uri=self.body_uri,
            role=self.role,
            mime_type=self.mime_type,
            size=self.size,
            path=self.path,
        )

    def to_resource_link(
        self,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> ResourceLinkContent:
        """Create a ResourceLinkContent pointing to this artifact's body."""
        return ResourceLinkContent(
            name=self.name,
            uri=self.body_uri,
            title=title or self.description,
            description=description,
            mimeType=self.mime_type,
            size=self.size,
        )

    def to_tool_result(
        self,
        *,
        summary: str | None = None,
        structured_content: dict[str, Any] | None = None,
        inline_body: str | None = None,
    ) -> ToolResult:
        """Create a ToolResult respecting inline thresholds.

        - size < INLINE_THRESHOLD: inline body (if provided) or summary + link
        - size < SUMMARY_THRESHOLD: summary + resource link
        - size >= SUMMARY_THRESHOLD: resource link only (handle-only)
        """
        from kaos_core.types.content import TextContent
        from kaos_core.types.results import ToolResult

        link = self.to_resource_link()
        content: list[TextContent | ResourceLinkContent] = []

        if self.size < INLINE_THRESHOLD and inline_body is not None:
            content.append(TextContent(text=inline_body))
        elif summary is not None:
            content.append(TextContent(text=summary))

        # Always include the resource link for non-tiny artifacts
        if self.size >= INLINE_THRESHOLD or inline_body is None:
            content.append(link)

        return ToolResult(
            content=content,  # type: ignore[arg-type]
            structuredContent=structured_content,
        )
