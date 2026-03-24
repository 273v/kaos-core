from __future__ import annotations

from typing import Any

from kaos_core import (
    DocumentationGenerator,
    KaosURI,
    TaskDefinition,
    TaskManager,
    TextContent,
    ToolCapability,
    ToolCategory,
    URITemplate,
    kaos_tool,
)


@kaos_tool(
    name="kaos-core-text-echo",
    description="Echo text",
    category=ToolCategory.TEXT,
    capability=ToolCapability.TRANSFORM,
    module_name="kaos-core",
    version="0.1.0",
    auto_register=False,
)
async def echo(text: str) -> str:
    return text


async def test_task_manager_and_uri_helpers() -> None:
    async def executor(definition: TaskDefinition) -> Any:
        return echo.validate_output(definition.inputs["text"])

    manager = TaskManager(executor=executor, enabled=True)
    created = await manager.create_task(
        TaskDefinition(
            task_id="task-1", name="Echo", tool_name="kaos-core-text-echo", inputs={"text": "ok"}
        )
    )
    status = await manager.wait_for_task(created.task_id, timeout=1.0)

    assert status.state.value == "completed"
    assert status.result is not None
    assert isinstance(status.result.content[0], TextContent)
    assert status.result.content[0].text == "ok"

    uri = KaosURI.parse("kaos://core/document/readme?version=1")
    assert uri.to_string() == "kaos://core/document/readme?version=1"
    assert URITemplate("kaos://{module}/document/{resource_id}").matches(
        "kaos://core/document/readme"
    ) == {
        "module": "core",
        "resource_id": "readme",
    }


def test_documentation_generator() -> None:
    card = DocumentationGenerator().generate_tool_card(echo)
    assert "# kaos-core-text-echo" in card
