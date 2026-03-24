from __future__ import annotations

import inspect
from typing import Any, get_type_hints

from kaos_core.base.tool import KaosTool


class ToolInspector:
    def get_source_info(self, tool: KaosTool) -> dict[str, Any]:
        execute = tool.execute
        module = inspect.getmodule(execute)
        return {
            "module": module.__name__ if module is not None else None,
            "qualname": getattr(execute, "__qualname__", "unknown"),
            "signature": str(inspect.signature(execute)),
        }

    def get_dependencies(self, tool: KaosTool) -> dict[str, Any]:
        return {"dependencies": tool.metadata.dependencies}

    def get_call_graph(self, tool: KaosTool) -> dict[str, Any]:
        execute = tool.execute
        return {"annotations": {key: str(value) for key, value in get_type_hints(execute).items()}}

    def get_complexity_metrics(self, tool: KaosTool) -> dict[str, Any]:
        source = inspect.getsource(tool.__class__)
        return {
            "source_lines": len(source.splitlines()),
            "input_count": len(tool.metadata.input_schema),
        }

    def generate_report(self, tool: KaosTool) -> str:
        source = self.get_source_info(tool)
        metrics = self.get_complexity_metrics(tool)
        return (
            f"Tool: {tool.metadata.name}\n"
            f"Module: {source['module']}\n"
            f"Signature: {source['signature']}\n"
            f"Source lines: {metrics['source_lines']}"
        )
