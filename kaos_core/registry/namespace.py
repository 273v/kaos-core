from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)  # Mutable: tool_count incremented by NamespaceManager.increment_tool_count()
class NamespaceInfo:
    namespace: str
    module_name: str
    version: str
    aliases: dict[str, str] = field(default_factory=dict)
    tool_count: int = 0


class NamespaceManager:
    def __init__(self) -> None:
        self._namespaces: dict[str, NamespaceInfo] = {}
        self._aliases: dict[str, str] = {}

    def claim_namespace(
        self,
        namespace: str,
        module_name: str,
        version: str,
        force: bool = False,
    ) -> bool:
        if namespace in self._namespaces and not force:
            return False
        self._namespaces[namespace] = NamespaceInfo(
            namespace=namespace,
            module_name=module_name,
            version=version,
        )
        return True

    def register_alias(self, alias: str, full_name: str) -> bool:
        self._aliases[alias] = full_name
        return True

    def resolve_name(self, name: str) -> str:
        return self._aliases.get(name, name)

    def validate_tool_name(self, name: str) -> bool:
        return name.count("-") >= 2 and "." not in name and "_" not in name

    def get_namespace_info(self, namespace: str) -> NamespaceInfo | None:
        return self._namespaces.get(namespace)

    def list_namespaces(self) -> list[str]:
        return sorted(self._namespaces)

    def increment_tool_count(self, namespace: str) -> None:
        if namespace in self._namespaces:
            self._namespaces[namespace].tool_count += 1

    def get_stats(self) -> dict[str, Any]:
        return {"namespaces": len(self._namespaces), "aliases": len(self._aliases)}
