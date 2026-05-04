from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from kaos_core.base.context import KaosContext
from kaos_core.exceptions import ValidationError
from kaos_core.types.metadata import ToolMetadata
from kaos_core.types.results import StreamingChunk, ToolResult


class KaosTool(ABC):
    is_initialized: bool

    def __init__(self) -> None:
        self.is_initialized = False

    @property
    @abstractmethod
    def metadata(self) -> ToolMetadata:
        raise NotImplementedError

    @abstractmethod
    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        raise NotImplementedError

    # Mapping from JSON Schema primitive `type` values to the Python types
    # that satisfy them. Tuples mean "any of these types are valid."
    # Note: `bool` is a subclass of `int` in Python, but JSON treats them as
    # distinct, so we reject booleans for numeric properties (and vice versa)
    # in the loop below.
    _JSON_SCHEMA_TYPE_MAP: ClassVar[dict[str, type | tuple[type, ...]]] = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
        "null": type(None),
    }

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        """Validate that ``inputs`` satisfy the tool's declared input schema.

        Checks performed:

        1. Every required property is present (missing required fields raise
           :class:`~kaos_core.exceptions.ValidationError`).
        2. Every provided property whose declared schema type is a JSON Schema
           primitive (``string``, ``integer``, ``number``, ``boolean``,
           ``array``, ``object``, ``null``) is checked for type compatibility.
           Type mismatches raise :class:`~kaos_core.exceptions.ValidationError`.

        Validation is intentionally limited to primitive type checks. Full
        JSON Schema validation (``enum``, ``minimum``/``maximum``, ``pattern``,
        nested ``properties``, ``oneOf``/``anyOf``, ``$ref``) is on the
        roadmap for v0.2 via the ``jsonschema`` library — see
        :issue:`<issue-link-once-filed>`. Subclasses are free to layer
        stricter validation on top of this method.
        """
        schema = self.metadata.get_input_json_schema()
        required = set(schema.get("required", []))
        missing = sorted(required.difference(inputs))
        if missing:
            raise ValidationError("Missing required inputs", fields=missing)

        properties = schema.get("properties", {})
        type_errors: list[str] = []
        for name, value in inputs.items():
            prop = properties.get(name)
            if not isinstance(prop, dict):
                continue
            declared = prop.get("type")
            expected = self._JSON_SCHEMA_TYPE_MAP.get(declared) if declared else None
            if expected is None:
                continue
            actual_name = type(value).__name__
            if declared in {"integer", "number"} and isinstance(value, bool):
                # bool is a subclass of int but is a distinct JSON type;
                # rejecting it here matches what jsonschema validators do.
                type_errors.append(f"{name}: expected {declared}, got boolean")
                continue
            if declared == "boolean" and not isinstance(value, bool):
                type_errors.append(f"{name}: expected boolean, got {actual_name}")
                continue
            if not isinstance(value, expected):
                type_errors.append(f"{name}: expected {declared}, got {actual_name}")
        if type_errors:
            raise ValidationError("Inputs failed type validation", fields=type_errors)

        return True

    async def stream_execute(
        self,
        inputs: dict[str, Any],
        context: KaosContext | None = None,
    ) -> AsyncIterator[StreamingChunk]:
        result = await self.execute(inputs, context=context)
        for index, item in enumerate(result.content):
            yield StreamingChunk(data=item, index=index, is_final=False)
        yield StreamingChunk(data=result.to_mcp_dict(), index=len(result.content), is_final=True)

    async def startup(self) -> None:
        self.is_initialized = True

    async def shutdown(self) -> None:
        self.is_initialized = False

    async def health_check(self) -> bool:
        return True

    def get_json_schema(self) -> dict[str, Any]:
        return self.metadata.get_input_json_schema()

    async def __aenter__(self) -> KaosTool:
        await self.startup()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.shutdown()

    def _repr_json_(self) -> dict[str, Any]:
        return self.metadata.to_mcp_dict()

    def _repr_markdown_(self) -> str:
        return f"### {self.metadata.name}\n\n{self.metadata.description}"

    def __str__(self) -> str:
        return self.metadata.name

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.metadata.name!r})"

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | {"execute", "metadata", "stream_execute"})

    @staticmethod
    def is_async_callable(candidate: Any) -> bool:
        return inspect.iscoroutinefunction(candidate)
