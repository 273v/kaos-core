from __future__ import annotations

from typing import Any, cast

from kaos_core import (
    DocumentationGenerator,
    ExecutionEngine,
    KaosContext,
    KaosResource,
    PromptTemplate,
    ResourceMetadata,
    ResourceType,
    SchemaExporter,
    ToolCapability,
    ToolCategory,
    kaos_tool,
)


class StaticResource(KaosResource):
    @property
    def metadata(self) -> ResourceMetadata:
        return ResourceMetadata(
            uri="kaos://core/document/readme",
            name="README",
            description="Repository readme",
            resource_type=ResourceType.DOCUMENT,
            provider_module="kaos-core",
            version="0.1.0",
        )

    async def read(self, context: Any = None) -> str:
        del context
        return "core-docs"

    async def get_metadata(self, context: Any = None) -> dict[str, str]:
        del context
        return {"kind": "static"}


@kaos_tool(
    name="kaos-core-docs-merge",
    description="Merge resource data with a prompt value",
    category=ToolCategory.DOCUMENT,
    capability=ToolCapability.TRANSFORM,
    module_name="kaos-core",
    version="0.1.0",
    auto_register=False,
)
async def merge(resource_text: str, suffix: str) -> dict[str, str]:
    return {"merged": f"{resource_text}:{suffix}"}


async def test_runtime_registration_execution_and_exports(runtime: Any) -> None:
    runtime.tools.register_tool(merge)
    runtime.resources.register_resource(StaticResource())
    runtime.prompts.register_prompt(PromptTemplate("Summarize {topic}"))

    context = KaosContext.create(runtime=runtime)
    resource_text = await context.read_resource("kaos://core/document/readme")
    engine = ExecutionEngine(runtime=runtime)
    execution = await engine.execute(
        "kaos-core-docs-merge", {"resource_text": resource_text, "suffix": "done"}
    )

    assert execution.output is not None
    assert execution.output.structuredContent == {"merged": "core-docs:done"}

    manifest = SchemaExporter().export_mcp_manifest(
        runtime.tools.list_tool_objects(),
        [runtime.resources._resources["kaos://core/document/readme"]],
        [runtime.prompts.get_prompt("kaos-template-prompt")],
    )
    docs = DocumentationGenerator().generate_api_reference(
        runtime.tools.list_tool_objects(),
        [runtime.resources._resources["kaos://core/document/readme"]],
        [runtime.prompts.get_prompt("kaos-template-prompt")],
    )

    manifest_data = cast(dict[str, list[dict[str, str]]], manifest)
    assert manifest_data["tools"][0]["name"] == "kaos-core-docs-merge"
    assert "kaos-core-docs-merge" in docs
