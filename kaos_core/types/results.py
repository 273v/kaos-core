from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

from pydantic import Field

from kaos_core.types.aliases import Cursor
from kaos_core.types.content import (
    ContentType,
    KaosModel,
    ResourceLinkContent,
    TextContent,
)


class ErrorInfo(KaosModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    traceback: str | None = None


class ToolResult(KaosModel):
    content: list[ContentType] = Field(default_factory=list)
    structuredContent: dict[str, Any] | None = None
    isError: bool = False
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")
    execution_time: float | None = Field(default=None, exclude=True)
    warnings: list[str] = Field(default_factory=list, exclude=True)
    progress: float | None = Field(default=None, exclude=True)
    next_cursor: Cursor | None = Field(default=None, exclude=True)

    @property
    def _meta(self) -> dict[str, Any] | None:
        return self.meta

    @classmethod
    def create_success(
        cls,
        output: str | dict[str, Any] | list[ContentType] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        content: list[ContentType]
        if isinstance(output, str):
            content = [TextContent(text=output)]
        elif isinstance(output, list):
            content = output
        else:
            content = cast(list[ContentType], kwargs.pop("content", []))
        structured = output if isinstance(output, dict) else kwargs.pop("structuredContent", None)
        return cls(content=content, structuredContent=structured, **kwargs)

    @classmethod
    def create_error(
        cls,
        error: str | ErrorInfo,
        **kwargs: Any,
    ) -> ToolResult:
        message = error.message if isinstance(error, ErrorInfo) else error
        content: list[ContentType] = [TextContent(text=message)]
        meta = kwargs.pop("_meta", kwargs.pop("meta", None))
        if isinstance(error, ErrorInfo):
            meta = {**(meta or {}), "error": error.model_dump(exclude_none=True)}
        return cls(content=content, isError=True, meta=meta, **kwargs)

    @classmethod
    def create_text(cls, text: str, **kwargs: Any) -> ToolResult:
        return cls(content=[TextContent(text=text)], **kwargs)

    @classmethod
    def create_resource_link(
        cls,
        uri: str,
        name: str,
        mime_type: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        return cls(
            content=[
                ResourceLinkContent(
                    name=name,
                    uri=uri,
                    mimeType=mime_type,
                )
            ],
            **kwargs,
        )

    @classmethod
    def create_summary_with_resource(
        cls,
        summary: str,
        *,
        uri: str,
        name: str | None = None,
        mime_type: str | None = None,
        structured_content: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        return cls(
            content=[
                TextContent(text=summary),
                ResourceLinkContent(
                    name=name or uri,
                    uri=uri,
                    mimeType=mime_type,
                ),
            ],
            structuredContent=structured_content,
            **kwargs,
        )

    def to_mcp_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)


class StreamingChunk(KaosModel):
    data: Any
    index: int
    is_final: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    cursor: Cursor | None = None


class StreamingResult:
    def __init__(self, iterator: AsyncIterator[StreamingChunk]) -> None:
        self._iterator = iterator

    async def chunks(self) -> AsyncIterator[StreamingChunk]:
        async for chunk in self._iterator:
            yield chunk

    async def collect(self) -> list[Any]:
        return [chunk.data async for chunk in self._iterator]


class ProgressUpdate(KaosModel):
    current: float
    total: float | None = None
    percentage: float | None = None
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_current(
        cls,
        current: float,
        total: float | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProgressUpdate:
        percentage = (current / total * 100.0) if total else None
        return cls(
            current=current,
            total=total,
            percentage=percentage,
            message=message,
            metadata=metadata or {},
        )


class ProgressResult:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[ProgressUpdate | ToolResult | None] = asyncio.Queue()
        self._result: ToolResult | None = None

    async def publish(self, update: ProgressUpdate) -> None:
        await self._queue.put(update)

    async def finish(self, result: ToolResult | None = None) -> None:
        self._result = result
        await self._queue.put(result)
        await self._queue.put(None)

    async def progress(self) -> AsyncIterator[ProgressUpdate]:
        while True:
            item = await self._queue.get()
            if item is None:
                break
            if isinstance(item, ProgressUpdate):
                yield item

    async def wait_for_completion(self) -> ToolResult | None:
        while self._result is None:
            item = await self._queue.get()
            if item is None:
                break
            if isinstance(item, ToolResult):
                self._result = item
        return self._result


class WorkflowResult(KaosModel):
    success: bool
    steps: list[ToolResult] = Field(default_factory=list)
    execution_time: float
    failed_step: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def successful_steps(self) -> int:
        return sum(not result.isError for result in self.steps)

    @property
    def failed_steps(self) -> int:
        return sum(result.isError for result in self.steps)
