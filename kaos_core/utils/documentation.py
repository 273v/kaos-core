from __future__ import annotations

from kaos_core.base.prompt import KaosPrompt
from kaos_core.base.resource import KaosResource
from kaos_core.base.tool import KaosTool


class DocumentationGenerator:
    def generate_tool_card(self, tool: KaosTool) -> str:
        metadata = tool.metadata
        return (
            f"# {metadata.name}\n\n"
            f"{metadata.description}\n\n"
            f"Category: {metadata.category.value}\n"
            f"Capability: {metadata.capability.value}\n"
        )

    def generate_resource_card(self, resource: KaosResource) -> str:
        metadata = resource.metadata
        return f"# {metadata.name}\n\n{metadata.description}\n\nURI: {metadata.uri}\n"

    def generate_api_reference(
        self,
        tools: list[KaosTool],
        resources: list[KaosResource],
        prompts: list[KaosPrompt] | None = None,
        title: str = "KAOS API Reference",
    ) -> str:
        sections = [f"# {title}"]
        sections.extend(self.generate_tool_card(tool) for tool in tools)
        sections.extend(self.generate_resource_card(resource) for resource in resources)
        if prompts:
            sections.extend(
                f"# {prompt.metadata.name}\n\n{prompt.metadata.description}\n" for prompt in prompts
            )
        return "\n\n".join(sections)

    def generate_module_summary(
        self,
        module_name: str,
        tools: list[KaosTool],
        resources: list[KaosResource],
    ) -> str:
        return f"# {module_name}\n\nTools: {len(tools)}\nResources: {len(resources)}\n"
