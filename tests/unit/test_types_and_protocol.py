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


def test_tool_result_typed_accessors() -> None:
    # Text accessor on string result
    text_result = ToolResult.create_success("hello")
    assert text_result.text == "hello"
    assert text_result.require_text() == "hello"

    # Text accessor on dict result with summary
    dict_result = ToolResult.create_success(output={"count": 5}, summary="Found 5 items")
    assert dict_result.text == "Found 5 items"
    assert dict_result.require_text() == "Found 5 items"
    assert dict_result.get_structured("count") == 5
    assert dict_result.get_structured("missing", "default") == "default"
    assert dict_result.require_structured() == {"count": 5}

    # Text accessor on dict result without summary
    bare_dict = ToolResult.create_success(output={"key": "value"})
    assert bare_dict.text is None
    assert bare_dict.get_structured("key") == "value"

    # Text accessor on empty result
    empty = ToolResult.create_success()
    assert empty.text is None
    assert empty.get_structured("anything") is None

    # require_text raises on non-text result
    import pytest

    with pytest.raises(ValueError, match="Expected TextContent"):
        empty.require_text()

    # require_structured raises on None
    with pytest.raises(ValueError, match="structuredContent is None"):
        empty.require_structured()


def test_task_state_values_are_stable() -> None:
    assert TaskState.COMPLETED.value == "completed"
    assert TextContent(text="ok").type == "text"
