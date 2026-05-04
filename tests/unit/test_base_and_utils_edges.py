from __future__ import annotations

from typing import Any, cast

from kaos_core import (
    KaosContext,
    KaosPrompt,
    KaosResource,
    KaosTool,
    PromptMetadata,
    ResourceMetadata,
    ResourceType,
    SchemaExporter,
    TextContent,
    ToolCapability,
    ToolCategory,
    ToolMetadata,
    ToolResult,
    WorkflowDefinition,
    WorkflowStep,
)
from kaos_core.types import Message
from kaos_core.utils import ToolInspector


class SampleTool(KaosTool):
    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="kaos-core-base-sample",
            description="sample tool",
            category=ToolCategory.UTILITY,
            capability=ToolCapability.TRANSFORM,
            module_name="kaos-core",
            version="0.1.0",
        )

    async def execute(
        self, inputs: dict[str, Any], context: KaosContext | None = None
    ) -> ToolResult:
        del inputs, context
        return ToolResult.create_text("ok")


class SamplePrompt(KaosPrompt):
    @property
    def metadata(self) -> PromptMetadata:
        return PromptMetadata(name="sample-prompt", description="sample", version="0.1.0")

    async def render(
        self,
        inputs: dict[str, Any],
        context: KaosContext | None = None,
    ) -> list[Message]:
        del inputs, context
        return []


class SampleResource(KaosResource):
    @property
    def metadata(self) -> ResourceMetadata:
        return ResourceMetadata(
            uri="kaos://core/document/base",
            name="base",
            description="base resource",
            resource_type=ResourceType.DOCUMENT,
            provider_module="kaos-core",
            version="0.1.0",
        )

    async def read(self, context: KaosContext | None = None) -> str:
        del context
        return "resource"

    async def get_metadata(self, context: KaosContext | None = None) -> dict[str, str]:
        del context
        return {"kind": "base"}


async def test_base_helpers_and_schema_export() -> None:
    tool = SampleTool()
    await tool.startup()
    stream = [chunk async for chunk in tool.stream_execute({})]
    await tool.shutdown()

    resource = SampleResource()
    prompt = SamplePrompt()
    tool_schema = SchemaExporter().export_tool_schema(tool)
    exported = SchemaExporter().export_mcp_manifest([tool], [resource], [prompt])
    report = ToolInspector().generate_report(tool)

    assert stream[-1].is_final is True
    assert isinstance(tool._repr_json_()["inputSchema"], dict)
    assert tool_schema == tool.get_json_schema()
    assert resource._repr_json_()["uri"] == "kaos://core/document/base"
    exported_manifest = cast(dict[str, list[dict[str, str]]], exported)
    assert exported_manifest["tools"][0]["name"] == "kaos-core-base-sample"
    assert "kaos-core-base-sample" in report


def test_workflow_definition_and_text_result() -> None:
    workflow = WorkflowDefinition(
        workflow_id="wf",
        name="wf",
        steps=[WorkflowStep(step_id="s1", tool_name="kaos-core-base-sample")],
    )
    result = ToolResult.create_text("done")

    assert workflow.steps[0].step_id == "s1"
    assert isinstance(result.content[0], TextContent)
