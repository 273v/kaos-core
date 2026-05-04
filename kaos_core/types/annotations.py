from __future__ import annotations

from pydantic import Field

from kaos_core.types.content import KaosModel


class ToolAnnotations(KaosModel):
    title: str | None = None
    readOnlyHint: bool = False
    destructiveHint: bool = False
    idempotentHint: bool = False
    openWorldHint: bool = True
    humanConfirmationRequired: bool = False


class ResourceAnnotations(KaosModel):
    audience: list[str] = Field(default_factory=lambda: ["user", "assistant"])
    priority: float = Field(default=0.0, ge=0.0, le=1.0)
