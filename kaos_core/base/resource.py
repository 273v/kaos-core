from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import uuid4

from kaos_core.base.context import KaosContext
from kaos_core.types.metadata import ResourceMetadata

Subscriber = Callable[[dict[str, Any]], Awaitable[None] | None]


class KaosResource(ABC):
    def __init__(self) -> None:
        self._subscribers: dict[str, Subscriber] = {}

    @property
    @abstractmethod
    def metadata(self) -> ResourceMetadata:
        raise NotImplementedError

    @abstractmethod
    async def read(self, context: KaosContext | None = None) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def get_metadata(self, context: KaosContext | None = None) -> dict[str, Any]:
        raise NotImplementedError

    async def stream_read(self, context: KaosContext | None = None) -> AsyncIterator[Any]:
        yield await self.read(context=context)

    async def subscribe_changes(self, callback: Subscriber) -> str:
        subscription_id = str(uuid4())
        self._subscribers[subscription_id] = callback
        return subscription_id

    async def unsubscribe_changes(self, subscription_id: str) -> None:
        self._subscribers.pop(subscription_id, None)

    async def _notify_subscribers(self, event: dict[str, Any]) -> None:
        for callback in self._subscribers.values():
            result = callback(event)
            if result is not None:
                await result

    def _repr_json_(self) -> dict[str, Any]:
        return self.metadata.to_mcp_dict()

    def _repr_markdown_(self) -> str:
        return f"### {self.metadata.name}\n\n{self.metadata.description}"

    def __str__(self) -> str:
        return self.metadata.uri

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(uri={self.metadata.uri!r})"

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | {"read", "stream_read", "metadata"})
