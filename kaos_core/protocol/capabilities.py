from __future__ import annotations

from typing import Any

from kaos_core.types.content import KaosModel


class RootsCapability(KaosModel):
    listChanged: bool = False


class ResourcesCapability(KaosModel):
    subscribe: bool = False
    listChanged: bool = False


class ClientCapabilities(KaosModel):
    sampling: dict[str, Any] | None = None
    elicitation: dict[str, Any] | None = None
    roots: RootsCapability | None = None
    experimental: dict[str, Any] | None = None


class ServerCapabilities(KaosModel):
    tools: dict[str, Any] | None = None
    resources: ResourcesCapability | None = None
    prompts: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None
    experimental: dict[str, Any] | None = None
