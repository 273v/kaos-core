from __future__ import annotations

import inspect
from collections.abc import Callable
from types import UnionType
from typing import Any, Literal, ParamSpec, TypeVar, Union, get_args, get_origin, get_type_hints

from kaos_core.base.context import KaosContext
from kaos_core.base.tool import KaosTool
from kaos_core.exceptions import ValidationError
from kaos_core.logging import get_logger
from kaos_core.registry.container import KaosRuntime
from kaos_core.types.annotations import ToolAnnotations
from kaos_core.types.enums import ToolCapability, ToolCategory
from kaos_core.types.metadata import ToolMetadata
from kaos_core.types.parameters import ParameterSchema
from kaos_core.types.results import ErrorInfo, ToolResult

P = ParamSpec("P")
R = TypeVar("R")
logger = get_logger(__name__)


def _annotation_to_schema(annotation: Any) -> tuple[str | list[str], dict[str, Any]]:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Literal:
        literal_values = list(args)
        literal_types = {_annotation_to_schema(type(value))[0] for value in literal_values}
        flattened_types: list[str] = []
        for type_value in literal_types:
            if isinstance(type_value, list):
                flattened_types.extend(type_value)
            else:
                flattened_types.append(type_value)
        unique_types = sorted(set(flattened_types))
        schema_type: str | list[str] = unique_types[0] if len(unique_types) == 1 else unique_types
        return schema_type, {"enum": literal_values}

    if origin in {list, tuple}:
        constraints: dict[str, Any] = {}
        if args and args[0] is not Any:
            item_type, item_constraints = _annotation_to_schema(args[0])
            constraints["items"] = {"type": item_type, **item_constraints}
        return "array", constraints

    if origin is dict:
        constraints = {}
        if len(args) == 2 and args[1] is not Any:
            value_type, value_constraints = _annotation_to_schema(args[1])
            constraints["additionalProperties"] = {"type": value_type, **value_constraints}
        return "object", constraints

    if origin in {Union, UnionType}:
        schema_types: list[str] = []
        for arg in args:
            arg_type, _arg_constraints = _annotation_to_schema(arg)
            if isinstance(arg_type, list):
                schema_types.extend(arg_type)
            else:
                schema_types.append(arg_type)
        unique_types = sorted(set(schema_types))
        return unique_types[0] if len(unique_types) == 1 else unique_types, {}

    schema_type = origin or annotation
    if schema_type is str:
        return "string", {}
    if schema_type is int:
        return "integer", {}
    if schema_type is float:
        return "number", {}
    if schema_type is bool:
        return "boolean", {}
    if schema_type is dict:
        return "object", {}
    if schema_type is list:
        return "array", {}
    if schema_type is type(None):
        return "null", {}
    if hasattr(schema_type, "model_json_schema"):
        model_schema = schema_type.model_json_schema()
        schema = dict(model_schema)
        type_value = schema.pop("type", "object")
        return type_value, schema
    return "string", {}


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
        expected = set(self._signature.parameters)
        if self._include_context:
            expected.discard("context")
        unexpected = sorted(set(inputs).difference(expected))
        if unexpected:
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
            logger.warning(
                "Function tool %s failed during execution (%s)",
                self.metadata.name,
                type(exc).__name__,
            )
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
            schema_type, constraints = _annotation_to_schema(annotation)
            input_schema.append(
                ParameterSchema(
                    name=parameter.name,
                    type=schema_type,
                    description=None,
                    required=parameter.default is inspect.Signature.empty,
                    default=None
                    if parameter.default is inspect.Signature.empty
                    else parameter.default,
                    constraints=constraints,
                )
            )
        output_annotation = type_hints.get("return")
        output_schema = None
        if output_annotation is not None and output_annotation is not ToolResult:
            schema_type, constraints = _annotation_to_schema(output_annotation)
            output_schema = {"type": schema_type, **constraints}
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
