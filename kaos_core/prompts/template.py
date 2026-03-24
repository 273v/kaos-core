from __future__ import annotations

from string import Formatter
from typing import Any, cast

from kaos_core.base.context import KaosContext
from kaos_core.base.prompt import KaosPrompt
from kaos_core.types.content import TextContent
from kaos_core.types.messages import Message
from kaos_core.types.metadata import PromptMetadata
from kaos_core.types.parameters import ParameterSchema


class TemplateVariable(ParameterSchema):
    var_type: str = "string"

    def validate_value(self, value: Any) -> None:
        if self.required and value is None:
            msg = f"Variable {self.name!r} is required"
            raise ValueError(msg)


class PromptTemplate(KaosPrompt):
    def __init__(
        self,
        template: str,
        *,
        variables: list[TemplateVariable] | None = None,
        metadata: PromptMetadata | None = None,
        delimiter: str = "{}",
    ) -> None:
        self.template = template
        self.delimiter = delimiter
        self._variables = variables or [
            TemplateVariable(name=name, type="string", required=True)
            for name in self._extract_variables(template)
        ]
        self._metadata = metadata or PromptMetadata(
            name="kaos-template-prompt",
            description="Template-backed prompt",
            version="0.1.0",
            input_schema=cast(list[ParameterSchema], list(self._variables)),
        )

    @property
    def metadata(self) -> PromptMetadata:
        return self._metadata

    def _extract_variables(self, template: str) -> list[str]:
        return [field_name for _, field_name, _, _ in Formatter().parse(template) if field_name]

    async def render(
        self,
        inputs: dict[str, Any],
        context: KaosContext | None = None,
    ) -> list[Message]:
        del context
        self.validate_inputs(inputs)
        rendered = self.template.format(**inputs)
        return [Message(role="user", content=TextContent(text=rendered))]

    def validate_inputs(self, inputs: dict[str, Any]) -> None:
        super().validate_inputs(inputs)
        for variable in self._variables:
            variable.validate_value(inputs.get(variable.name))

    def get_variables(self) -> list[str]:
        return [variable.name for variable in self._variables]

    def add_variable(self, variable: TemplateVariable) -> None:
        self._variables.append(variable)
        self._metadata = self._metadata.model_copy(update={"input_schema": self._variables})

    def format_partial(self, **kwargs: Any) -> PromptTemplate:
        safe_kwargs = {key: value for key, value in kwargs.items() if key in self.get_variables()}
        rendered = self.template.format_map(_PartialFormatter(safe_kwargs))
        remaining = [variable for variable in self._variables if variable.name not in safe_kwargs]
        metadata = self._metadata.model_copy(update={"input_schema": remaining})
        return PromptTemplate(
            rendered, variables=remaining, metadata=metadata, delimiter=self.delimiter
        )


class _PartialFormatter(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
