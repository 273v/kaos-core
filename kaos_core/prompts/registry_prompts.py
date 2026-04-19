from __future__ import annotations

from kaos_core.prompts.template import PromptTemplate, TemplateVariable
from kaos_core.types.metadata import PromptMetadata


def build_system_prompt() -> PromptTemplate:
    return PromptTemplate(
        (
            "You are operating inside KAOS. Prioritize correctness, clear reasoning, "
            "and safe tool usage.\n\nTask: {task}"
        ),
        variables=[TemplateVariable(name="task", type="string", description="Task description")],
        metadata=PromptMetadata(
            name="kaos-system-task",
            description="Default KAOS system prompt",
            version="0.1.0",
            provider_module="kaos-core",
        ),
    )
