from __future__ import annotations

from kaos_core._version import __version__ as _kaos_core_version
from kaos_core.base.prompt import KaosPrompt
from kaos_core.base.resource import KaosResource
from kaos_core.base.tool import KaosTool


class SchemaExporter:
    """Serialise tools, resources, and prompts to portable schema formats.

    The generated OpenAPI document conforms to OpenAPI Specification 3.1.0;
    every operation declares ``info`` and at least one response, which the
    spec requires.
    """

    def export_tool_schema(self, tool: KaosTool) -> dict[str, object]:
        return tool.get_json_schema()

    def export_openapi(
        self,
        tools: list[KaosTool],
        *,
        title: str = "KAOS Tools",
        version: str = _kaos_core_version,
        description: str | None = None,
    ) -> dict[str, object]:
        """Build an OpenAPI 3.1.0 document describing ``tools``.

        Each tool is exposed as a ``POST /tools/<name>`` operation whose
        request body is the tool's input JSON Schema. The success response
        echoes a permissive ``application/json`` ``ToolResult`` body; the
        ``400`` and ``500`` responses give consumers a place to hang typed
        error handling without fabricating shapes the runtime does not yet
        guarantee.
        """
        info: dict[str, object] = {"title": title, "version": version}
        if description is not None:
            info["description"] = description

        tool_result_response: dict[str, object] = {
            "description": "Tool executed successfully.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "description": (
                            "Serialised kaos_core.types.results.ToolResult; "
                            "see the ToolResult model for the canonical shape."
                        ),
                    }
                }
            },
        }
        validation_error_response: dict[str, object] = {
            "description": "Inputs failed schema or contract validation.",
        }
        execution_error_response: dict[str, object] = {
            "description": "Tool executed but raised an unrecoverable error.",
        }

        paths: dict[str, object] = {
            f"/tools/{tool.metadata.name}": {
                "post": {
                    "operationId": f"invoke_{tool.metadata.name.replace('-', '_')}",
                    "summary": tool.metadata.description,
                    "tags": [tool.metadata.module_name or "kaos"],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": tool.get_json_schema()}},
                    },
                    "responses": {
                        "200": tool_result_response,
                        "400": validation_error_response,
                        "500": execution_error_response,
                    },
                }
            }
            for tool in tools
        }

        return {
            "openapi": "3.1.0",
            "info": info,
            "paths": paths,
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
