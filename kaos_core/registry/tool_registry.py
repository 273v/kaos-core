from __future__ import annotations

from typing import Any

from kaos_core.base.tool import KaosTool
from kaos_core.exceptions import RegistryError
from kaos_core.types.enums import ToolCapability, ToolCategory
from kaos_core.types.metadata import ToolMetadata


class ToolRegistry:
    def __init__(self, namespace_manager: Any | None = None) -> None:
        self._tools: dict[str, KaosTool] = {}
        self._aliases: dict[str, str] = {}
        self._namespace_manager = namespace_manager

    def register_tool(self, tool: KaosTool, aliases: list[str] | None = None) -> None:
        name = tool.metadata.name
        if name in self._tools:
            raise RegistryError("Tool already registered", tool_name=name)
        self._tools[name] = tool
        namespace = name.split("-", 2)[0:2]
        if self._namespace_manager is not None and len(namespace) >= 2:
            namespace_name = "-".join(namespace)
            self._namespace_manager.claim_namespace(
                namespace_name,
                module_name=tool.metadata.module_name,
                version=tool.metadata.version,
            )
            self._namespace_manager.increment_tool_count(namespace_name)
        for alias in aliases or []:
            self._aliases[alias] = name
            if self._namespace_manager is not None:
                self._namespace_manager.register_alias(alias, name)

    def get_tool(self, name: str) -> KaosTool | None:
        resolved = self._aliases.get(name, name)
        return self._tools.get(resolved)

    def search_tools(
        self,
        *,
        category: ToolCategory | None = None,
        capability: ToolCapability | None = None,
        tags: list[str] | None = None,
        query: str | None = None,
        namespace: str | None = None,
    ) -> list[ToolMetadata]:
        results: list[ToolMetadata] = []
        for tool in self._tools.values():
            metadata = tool.metadata
            if category and metadata.category != category:
                continue
            if capability and metadata.capability != capability:
                continue
            if tags and not set(tags).issubset(metadata.tags):
                continue
            if query and query.lower() not in f"{metadata.name} {metadata.description}".lower():
                continue
            if namespace and not metadata.name.startswith(namespace):
                continue
            results.append(metadata)
        return results

    def get_tool_schema(self, name: str) -> dict[str, Any] | None:
        tool = self.get_tool(name)
        return None if tool is None else tool.get_json_schema()

    def find_compatible_tools(
        self,
        *,
        input_type: str | None = None,
        output_type: str | None = None,
    ) -> list[str]:
        matches: list[str] = []
        for tool in self._tools.values():
            input_types = {parameter.type for parameter in tool.metadata.input_schema}
            if input_type and input_type not in input_types:
                continue
            if (
                output_type
                and tool.metadata.output_schema is not None
                and tool.metadata.output_schema.get("type") != output_type
            ):
                continue
            matches.append(tool.metadata.name)
        return matches

    def get_tool_hierarchy(self) -> dict[str, list[str]]:
        hierarchy: dict[str, list[str]] = {}
        for name in self._tools:
            namespace = "-".join(name.split("-")[:2])
            hierarchy.setdefault(namespace, []).append(name)
        return {key: sorted(value) for key, value in hierarchy.items()}

    def list_namespaces(self) -> list[str]:
        return sorted({"-".join(name.split("-")[:2]) for name in self._tools})

    def list_tools(self) -> list[str]:
        return sorted(self._tools)

    def list_tool_objects(self) -> list[KaosTool]:
        return list(self._tools.values())

    def get_tools(self, names: list[str] | None = None) -> dict[str, KaosTool]:
        if names is None:
            return dict(self._tools)
        return {name: tool for name in names if (tool := self.get_tool(name)) is not None}

    def get_stats(self) -> dict[str, int]:
        return {"tools": len(self._tools), "aliases": len(self._aliases)}
