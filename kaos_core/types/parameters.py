from __future__ import annotations

from typing import Any

from pydantic import Field

from kaos_core.types.content import KaosModel


class ParameterSchema(KaosModel):
    name: str
    type: str | list[str]
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
        # OpenAI's strict JSON Schema validator rejects `type=array` without
        # `items`. Anthropic accepts it. Without this floor, a single bridged
        # tool that forgot to declare item types breaks the entire turn for
        # OpenAI-provider sessions — the LLM can't see ANY tool. Default to
        # the universal-accept `items: {}` so callers get a valid schema even
        # when they forget to type their array elements; well-typed callers
        # override by setting `constraints["items"]` explicitly.
        if schema["type"] == "array" and "items" not in schema:
            schema["items"] = {}
        return schema
