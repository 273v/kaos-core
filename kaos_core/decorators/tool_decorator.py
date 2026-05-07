from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, get_origin, get_type_hints

from kaos_core.base.context import KaosContext
from kaos_core.base.tool import KaosTool
from kaos_core.exceptions import ValidationError
from kaos_core.registry.container import KaosRuntime
from kaos_core.types.annotations import ToolAnnotations
from kaos_core.types.enums import ToolCapability, ToolCategory
from kaos_core.types.metadata import ToolMetadata
from kaos_core.types.parameters import ParameterSchema
from kaos_core.types.results import ErrorInfo, ToolResult

P = ParamSpec("P")
R = TypeVar("R")


def _annotation_to_schema(annotation: Any) -> str:
    origin = get_origin(annotation)
    schema_type = origin or annotation
    if schema_type is str:
        return "string"
    if schema_type is int:
        return "integer"
    if schema_type is float:
        return "number"
    if schema_type is bool:
        return "boolean"
    if schema_type is dict:
        return "object"
    if schema_type is list:
        return "array"
    if schema_type is type(None):
        return "null"
    return "string"


def _structured_summary(tool_name: str, output: dict[str, Any]) -> str:
    field_count = len(output)
    suffix = "" if field_count == 1 else "s"
    if not output:
        return f"{tool_name} returned structured data with 0 fields."
    keys = sorted(str(key) for key in output)[:5]
    key_list = ", ".join(keys)
    if field_count > len(keys):
        key_list = f"{key_list}, ..."
    return f"{tool_name} returned structured data with {field_count} field{suffix}: {key_list}."


class FunctionTool(KaosTool):
    def __init__(
        self,
        func: Callable[..., Any],
        *,
        metadata: ToolMetadata,
        include_context: bool = False,
    ) -> None:
        super().__init__()
        self._func = func
        self._metadata = metadata
        self._include_context = include_context
        self._signature = inspect.signature(func)
        self._type_hints = get_type_hints(func)

    @property
    def metadata(self) -> ToolMetadata:
        return self._metadata

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        super().validate_inputs(inputs)
        unexpected = sorted(set(inputs).difference(self._signature.parameters))
        if unexpected and not self._include_context:
            raise ValidationError("Unexpected inputs", fields=unexpected)
        return True

    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        self.validate_inputs(inputs)
        call_args = dict(inputs)
        if self._include_context:
            call_args["context"] = context
        try:
            result = self._func(**call_args)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            return ToolResult.create_error(
                ErrorInfo(
                    code="function_tool_execution_failed",
                    message=(
                        f"Tool {self.metadata.name} failed during execution. "
                        "Check the inputs and runtime state, then retry. "
                        "For implementation debugging, call the wrapped function directly."
                    ),
                    details={
                        "tool_name": self.metadata.name,
                        "exception_type": type(exc).__name__,
                        "exception": str(exc),
                    },
                )
            )
        return self.validate_output(result)

    def validate_output(self, output: Any) -> ToolResult:
        if isinstance(output, ToolResult):
            return output
        if isinstance(output, str):
            return ToolResult.create_text(output)
        if isinstance(output, dict):
            return ToolResult.create_success(
                output,
                summary=_structured_summary(self.metadata.name, output),
            )
        return ToolResult.create_text(str(output))


def kaos_tool(
    *,
    name: str | None = None,
    display_name: str | None = None,
    description: str | None = None,
    category: ToolCategory = ToolCategory.DATA,
    capability: ToolCapability = ToolCapability.TRANSFORM,
    module_name: str = "decorated",
    version: str = "1.0.0",
    tags: list[str] | None = None,
    auto_register: bool = False,
    include_context: bool = False,
    annotations: ToolAnnotations | None = None,
) -> Callable[[Callable[P, R]], FunctionTool]:
    def decorator(func: Callable[P, R]) -> FunctionTool:
        func_name = getattr(func, "__name__", func.__class__.__name__)
        type_hints = get_type_hints(func)
        signature = inspect.signature(func)
        input_schema: list[ParameterSchema] = []
        for parameter in signature.parameters.values():
            if include_context and parameter.name == "context":
                continue
            annotation = type_hints.get(parameter.name, str)
            input_schema.append(
                ParameterSchema(
                    name=parameter.name,
                    type=_annotation_to_schema(annotation),
                    description=None,
                    required=parameter.default is inspect.Signature.empty,
                    default=None
                    if parameter.default is inspect.Signature.empty
                    else parameter.default,
                )
            )
        output_annotation = type_hints.get("return")
        output_schema = None
        if output_annotation is not None and output_annotation is not ToolResult:
            output_schema = {"type": _annotation_to_schema(output_annotation)}
        metadata = ToolMetadata(
            name=name or func_name.replace("_", "-"),
            display_name=display_name,
            description=description or (inspect.getdoc(func) or f"Execute {func_name}"),
            category=category,
            capability=capability,
            tags=tags or [],
            input_schema=input_schema,
            output_schema=output_schema,
            module_name=module_name,
            version=version,
            annotations=annotations or ToolAnnotations(),
        )
        tool = FunctionTool(func, metadata=metadata, include_context=include_context)
        if auto_register:
            KaosRuntime.default().tools.register_tool(tool)
        return tool

    return decorator
