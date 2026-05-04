from __future__ import annotations

from typing import Any

from pydantic import Field

from kaos_core.types.content import KaosModel


class ParameterSchema(KaosModel):
    name: str
    type: str
    description: str | None = None
    required: bool = True
    default: Any = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    examples: list[Any] = Field(default_factory=list)

    def to_json_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type}
        if self.description:
            schema["description"] = self.description
        if self.examples:
            schema["examples"] = self.examples
        schema.update(self.constraints)
        if not self.required and self.default is not None:
            schema["default"] = self.default
        return schema
