from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from kaos_core.base.context import KaosContext
from kaos_core.exceptions import ValidationError
from kaos_core.types.messages import Message
from kaos_core.types.metadata import PromptMetadata


class KaosPrompt(ABC):
    @property
    @abstractmethod
    def metadata(self) -> PromptMetadata:
        raise NotImplementedError

    @abstractmethod
    async def render(
        self,
        inputs: dict[str, Any],
        context: KaosContext | None = None,
    ) -> list[Message]:
        raise NotImplementedError

    def validate_inputs(self, inputs: dict[str, Any]) -> None:
        required = {
            parameter.name for parameter in self.metadata.input_schema if parameter.required
        }
        missing = sorted(required.difference(inputs))
        if missing:
            raise ValidationError("Missing prompt variables", variables=missing)

    def get_variables(self) -> list[str]:
        return [parameter.name for parameter in self.metadata.input_schema]

    def get_examples(self) -> list[dict[str, Any]]:
        return self.metadata.examples

    async def render_batch(
        self,
        batch_inputs: list[dict[str, Any]],
        context: KaosContext | None = None,
    ) -> list[list[Message]]:
        return [await self.render(inputs, context=context) for inputs in batch_inputs]
