from __future__ import annotations

from kaos_core.base.prompt import KaosPrompt
from kaos_core.base.resource import KaosResource
from kaos_core.base.tool import KaosTool


class SchemaExporter:
    def export_tool_schema(self, tool: KaosTool) -> dict[str, object]:
        return tool.get_json_schema()

    def export_openapi(self, tools: list[KaosTool]) -> dict[str, object]:
        return {
            "openapi": "3.1.0",
            "paths": {
                f"/tools/{tool.metadata.name}": {
                    "post": {
                        "summary": tool.metadata.description,
                        "requestBody": {
                            "content": {"application/json": {"schema": tool.get_json_schema()}}
                        },
                    }
                }
                for tool in tools
            },
        }

    def export_mcp_manifest(
        self,
        tools: list[KaosTool],
        resources: list[KaosResource],
        prompts: list[KaosPrompt],
    ) -> dict[str, object]:
        return {
            "tools": [tool.metadata.to_mcp_dict() for tool in tools],
            "resources": [resource.metadata.to_mcp_dict() for resource in resources],
            "prompts": [prompt.metadata.to_mcp_dict() for prompt in prompts],
        }
