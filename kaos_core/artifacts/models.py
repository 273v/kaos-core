from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import Field

from kaos_core.artifacts.settings import KaosCoreArtifactSettings
from kaos_core.types.content import KaosModel, ResourceLinkContent
from kaos_core.types.enums import ArtifactRetentionPolicy, ArtifactRole

if TYPE_CHECKING:
    from kaos_core.types.results import ToolResult

# ---------------------------------------------------------------------------
# Inline threshold constants (bytes) — defaults exposed as module-level names
# for backward compatibility. The authoritative source is
# :class:`KaosCoreArtifactSettings` (env-overridable, context-overridable).
# ---------------------------------------------------------------------------
_DEFAULT_ARTIFACT_SETTINGS = KaosCoreArtifactSettings()
INLINE_THRESHOLD = _DEFAULT_ARTIFACT_SETTINGS.inline_threshold
SUMMARY_THRESHOLD = _DEFAULT_ARTIFACT_SETTINGS.summary_threshold


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
    source_uri: str | None = None
    """Originating URI for materialised content (e.g. ``https://www.federalregister.gov/...``).

    First-class because downstream agents and the SPA need to render
    provenance ("where did this come from?") without spelunking the
    free-form ``provenance`` or ``metadata`` dicts. ``None`` for purely
    derived or user-uploaded artifacts.
    """
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
        settings: KaosCoreArtifactSettings | None = None,
    ) -> ToolResult:
        """Create a ToolResult respecting inline thresholds.

        Tiers (thresholds resolved from ``settings`` or
        :class:`KaosCoreArtifactSettings` defaults; both env-overridable):

        - size < ``inline_threshold``: inline body (if provided) or summary + link
        - size < ``summary_threshold``: summary + resource link
        - size >= ``summary_threshold``: resource link only (handle-only)
        """
        from kaos_core.types.content import TextContent
        from kaos_core.types.results import ToolResult

        resolved = settings or _DEFAULT_ARTIFACT_SETTINGS
        inline_threshold = resolved.inline_threshold
        summary_threshold = resolved.summary_threshold

        link = self.to_resource_link()
        content: list[TextContent | ResourceLinkContent] = []

        if self.size < inline_threshold and inline_body is not None:
            content.append(TextContent(text=inline_body))
        elif self.size < summary_threshold and summary is not None:
            content.append(TextContent(text=summary))

        # Always include the resource link for non-tiny artifacts
        if self.size >= inline_threshold or inline_body is None:
            content.append(link)

        return ToolResult(
            # `list` is invariant in its parameter; the local
            # `list[TextContent | ResourceLinkContent]` cannot widen to
            # `list[ContentType]` even though every element is assignable.
            content=content,
            structuredContent=structured_content,
        )
