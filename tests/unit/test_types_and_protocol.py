from __future__ import annotations

from kaos_core.protocol import ClientCapabilities, Implementation, InitializeRequest
from kaos_core.types import (
    ParameterSchema,
    TaskState,
    TextContent,
    ToolAnnotations,
    ToolCapability,
    ToolCategory,
    ToolMetadata,
    ToolResult,
)


def test_tool_metadata_and_result_are_mcp_native() -> None:
    metadata = ToolMetadata(
        name="kaos-core-text-echo",
        description="Echo text",
        category=ToolCategory.TEXT,
        capability=ToolCapability.TRANSFORM,
        input_schema=[ParameterSchema(name="text", type="string")],
        module_name="kaos-core",
        version="0.1.0",
        annotations=ToolAnnotations(readOnlyHint=True),
    )

    assert metadata.to_mcp_dict()["inputSchema"]["required"] == ["text"]

    result = ToolResult.create_success({"echo": "hello"}, _meta={"trace": "abc"})
    payload = result.to_mcp_dict()

    assert payload["structuredContent"] == {"echo": "hello"}
    assert payload["_meta"] == {"trace": "abc"}
    assert payload["isError"] is False


def test_protocol_models_round_trip() -> None:
    request = InitializeRequest(
        protocol_version="2025-11-25",
        capabilities=ClientCapabilities(sampling={"enabled": True}),
        client_info=Implementation(name="pytest", version="1.0.0"),
    )

    dumped = request.model_dump()
    restored = InitializeRequest.model_validate(dumped)

    assert restored.protocol_version == "2025-11-25"
    assert restored.capabilities.sampling == {"enabled": True}


def test_task_state_values_are_stable() -> None:
    assert TaskState.COMPLETED.value == "completed"
    assert TextContent(text="ok").type == "text"
