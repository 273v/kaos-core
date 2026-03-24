from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class KaosModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TextContent(KaosModel):
    type: Literal["text"] = "text"
    text: str


class ImageContent(KaosModel):
    type: Literal["image"] = "image"
    data: str
    mimeType: str = Field(..., description="Media type for the base64 payload.")


class AudioContent(KaosModel):
    type: Literal["audio"] = "audio"
    data: str
    mimeType: str = Field(..., description="Media type for the base64 payload.")


class EmbeddedResource(KaosModel):
    type: Literal["resource"] = "resource"
    resource: dict[str, Any]


type ContentType = TextContent | ImageContent | AudioContent | EmbeddedResource
