from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator

from kaos_core.types.annotations import ResourceAnnotations, ToolAnnotations
from kaos_core.types.content import KaosModel
from kaos_core.types.enums import ResourceType, ToolCapability, ToolCategory
from kaos_core.types.parameters import ParameterSchema

TOOL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){2,}$")


class ToolMetadata(KaosModel):
    name: str
    display_name: str | None = None
    description: str
    icon: str | None = None
    category: ToolCategory
    capability: ToolCapability
    tags: list[str] = Field(default_factory=list)
    input_schema: list[ParameterSchema] = Field(default_factory=list)
    output_schema: dict[str, Any] | None = None
    estimated_duration: float | None = Field(default=None, ge=0.0)
    resource_requirements: dict[str, Any] = Field(default_factory=dict)
    side_effects: bool = False
    idempotent: bool = True
    supports_tasks: bool = False
    module_name: str
    version: str
    dependencies: list[str] = Field(default_factory=list)
    annotations: ToolAnnotations | None = None

    @field_validator("name")
    @classmethod
    def validate_hierarchical_name(cls, value: str) -> str:
        if not TOOL_NAME_PATTERN.match(value):
            msg = "Tool names must use MCP-safe hyphen-separated segments"
            raise ValueError(msg)
        return value

    def get_input_json_schema(self) -> dict[str, Any]:
        required = [parameter.name for parameter in self.input_schema if parameter.required]
        properties = {parameter.name: parameter.to_json_schema() for parameter in self.input_schema}
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    def to_mcp_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.get_input_json_schema(),
        }
        if self.display_name:
            payload["title"] = self.display_name
        if self.output_schema is not None:
            payload["outputSchema"] = self.output_schema
        if self.icon:
            payload["icon"] = self.icon
        if self.annotations is not None:
            payload["annotations"] = self.annotations.model_dump(exclude_none=True)
        return payload


class ResourceMetadata(KaosModel):
    uri: str
    name: str
    description: str
    icon: str | None = None
    resource_type: ResourceType
    tags: list[str] = Field(default_factory=list)
    size: int | None = Field(default=None, ge=0)
    created_at: str | None = None
    modified_at: str | None = None
    checksum: str | None = None
    mime_type: str | None = None
    access_pattern: str | None = None
    requires_authentication: bool = False
    supports_subscription: bool = False
    annotations: ResourceAnnotations | None = None
    provider_module: str
    version: str
    template_uri: str | None = None
    template_parameters: list[str] = Field(default_factory=list)

    def to_mcp_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
        }
        if self.mime_type:
            payload["mimeType"] = self.mime_type
        if self.icon:
            payload["icon"] = self.icon
        if self.annotations is not None:
            payload["annotations"] = self.annotations.model_dump(exclude_none=True)
        return payload


class PromptMetadata(KaosModel):
    name: str
    description: str
    version: str
    author: str | None = None
    icon: str | None = None
    tags: list[str] = Field(default_factory=list)
    category: str | None = None
    input_schema: list[ParameterSchema] = Field(default_factory=list)
    output_schema: dict[str, Any] | None = None
    examples: list[dict[str, Any]] = Field(default_factory=list)
    provider_module: str | None = None
    documentation_url: str | None = None

    def to_mcp_dict(self) -> dict[str, Any]:
        arguments = [
            {
                "name": parameter.name,
                "description": parameter.description,
                "required": parameter.required,
            }
            for parameter in self.input_schema
        ]
        payload: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "arguments": arguments,
        }
        if self.icon:
            payload["icon"] = self.icon
        return payload
