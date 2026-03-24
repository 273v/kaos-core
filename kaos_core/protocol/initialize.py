from __future__ import annotations

from kaos_core.protocol.capabilities import ClientCapabilities, ServerCapabilities
from kaos_core.types.content import KaosModel


class Implementation(KaosModel):
    name: str
    version: str


class InitializeRequest(KaosModel):
    protocol_version: str
    capabilities: ClientCapabilities
    client_info: Implementation


class InitializeResult(KaosModel):
    protocol_version: str
    capabilities: ServerCapabilities
    server_info: Implementation
    instructions: str | None = None
