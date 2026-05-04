from __future__ import annotations

from typing import Literal

from kaos_core.types.content import ContentType, KaosModel


class Message(KaosModel):
    role: Literal["user", "assistant"]
    content: ContentType


class SamplingMessage(KaosModel):
    role: Literal["user", "assistant"]
    content: ContentType


class UserMessage(Message):
    role: Literal["user"] = "user"


class AssistantMessage(Message):
    role: Literal["assistant"] = "assistant"
