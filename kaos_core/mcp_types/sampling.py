from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from kaos_core.types.content import ContentType, KaosModel
from kaos_core.types.messages import SamplingMessage


class ModelHint(KaosModel):
    name: str | None = None


class ModelPreferences(KaosModel):
    hints: list[ModelHint] = Field(default_factory=list)
    cost_priority: float = Field(default=0.0, ge=0.0, le=1.0)
    speed_priority: float = Field(default=0.0, ge=0.0, le=1.0)
    intelligence_priority: float = Field(default=0.0, ge=0.0, le=1.0)


class SamplingRequest(KaosModel):
    messages: list[SamplingMessage]
    model_preferences: ModelPreferences | None = None
    system_prompt: str | None = None
    # MCP SamplingRequest budget. 256 was a 2023-era safeguard from when
    # MCP clients delegated to expensive APIs and wanted a hard floor.
    # In 2026 we want sampling to actually be useful — bumping to 32K
    # lets a sub-call produce a real answer.
    max_tokens: int = Field(default=32_768, gt=0)
    temperature: float | None = None
    stop_sequences: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SamplingResponse(KaosModel):
    role: Literal["assistant"] = "assistant"
    content: ContentType
    model: str
    stop_reason: str | None = None
