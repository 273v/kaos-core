from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from kaos_core.base.context import KaosContext
from kaos_core.exceptions import ValidationError
from kaos_core.types.metadata import ToolMetadata
from kaos_core.types.results import StreamingChunk, ToolResult


class KaosTool(ABC):
    is_initialized: bool

    def __init__(self) -> None:
        self.is_initialized = False

    @property
    @abstractmethod
    def metadata(self) -> ToolMetadata:
        raise NotImplementedError

    @abstractmethod
    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        raise NotImplementedError

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        schema = self.metadata.get_input_json_schema()
        required = set(schema.get("required", []))
        missing = sorted(required.difference(inputs))
        if missing:
            raise ValidationError("Missing required inputs", fields=missing)
        return True

    async def stream_execute(
        self,
        inputs: dict[str, Any],
        context: KaosContext | None = None,
    ) -> AsyncIterator[StreamingChunk]:
        result = await self.execute(inputs, context=context)
        for index, item in enumerate(result.content):
            yield StreamingChunk(data=item, index=index, is_final=False)
        yield StreamingChunk(data=result.to_mcp_dict(), index=len(result.content), is_final=True)

    async def startup(self) -> None:
        self.is_initialized = True

    async def shutdown(self) -> None:
        self.is_initialized = False

    async def health_check(self) -> bool:
        return True

    def get_json_schema(self) -> dict[str, Any]:
        return self.metadata.get_input_json_schema()

    async def __aenter__(self) -> KaosTool:
        await self.startup()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.shutdown()

    def _repr_json_(self) -> dict[str, Any]:
        return self.metadata.to_mcp_dict()

    def _repr_markdown_(self) -> str:
        return f"### {self.metadata.name}\n\n{self.metadata.description}"

    def __str__(self) -> str:
        return self.metadata.name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.metadata.name!r})"

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | {"execute", "metadata", "stream_execute"})

    @staticmethod
    def is_async_callable(candidate: Any) -> bool:
        return inspect.iscoroutinefunction(candidate)
