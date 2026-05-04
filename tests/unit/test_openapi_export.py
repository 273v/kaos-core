"""Tests for SchemaExporter.export_openapi.

Pins the contract that the generated document is a valid OpenAPI 3.1.0
shape: required ``info`` (with ``title`` and ``version``), every operation
declares at least one response, request bodies declare a content type.
"""

from __future__ import annotations

from typing import Any, cast

from kaos_core import (
    SchemaExporter,
    ToolCapability,
    ToolCategory,
    kaos_tool,
)


@kaos_tool(
    name="kaos-test-openapi-add",
    description="Add two integers",
    category=ToolCategory.DATA,
    capability=ToolCapability.TRANSFORM,
    auto_register=False,
)
async def add(a: int, b: int) -> int:
    return a + b


@kaos_tool(
    name="kaos-test-openapi-greet",
    description="Greet a name",
    category=ToolCategory.TEXT,
    capability=ToolCapability.TRANSFORM,
    auto_register=False,
)
async def greet(name: str) -> str:
    return f"hello {name}"


def _doc(*tools: Any, **info: Any) -> dict[str, Any]:
    """Helper: cast SchemaExporter output to dict[str, Any] for test access.

    The exporter returns ``dict[str, object]`` (correct, since values are
    heterogeneous). Tests assert specific shapes against the result, so
    we narrow to ``dict[str, Any]`` once at the entrypoint rather than
    sprinkling ``cast`` everywhere.
    """
    return cast(dict[str, Any], SchemaExporter().export_openapi(list(tools), **info))


def test_openapi_doc_has_top_level_required_fields() -> None:
    doc = _doc(add, greet)
    assert doc["openapi"] == "3.1.0"
    assert "info" in doc, "OpenAPI 3.1 requires an `info` object"
    assert "paths" in doc

    info = doc["info"]
    # OAS 3.1 requires both info.title and info.version.
    assert "title" in info
    assert "version" in info


def test_openapi_doc_overrides_info_fields() -> None:
    doc = _doc(add, title="my service", version="9.9.9", description="things and stuff")
    info = doc["info"]
    assert info["title"] == "my service"
    assert info["version"] == "9.9.9"
    assert info["description"] == "things and stuff"


def test_every_operation_declares_at_least_one_response() -> None:
    doc = _doc(add, greet)
    paths = doc["paths"]
    assert len(paths) == 2

    for path, item in paths.items():
        post = item["post"]
        # OAS 3.1 requires `responses` to be present and non-empty on every
        # operation. https://spec.openapis.org/oas/v3.1.0.html#operation-object
        responses = post.get("responses")
        assert isinstance(responses, dict), f"{path} is missing responses"
        assert responses, f"{path} has empty responses"
        # We also include the success path explicitly so consumers always
        # see at least one documented success contract.
        assert "200" in responses, f"{path} is missing the 200 response"


def test_request_body_declares_application_json_content() -> None:
    doc = _doc(add)
    path_item = doc["paths"]["/tools/kaos-test-openapi-add"]
    post = path_item["post"]
    body = post["requestBody"]
    content = body["content"]
    assert "application/json" in content
    schema = content["application/json"]["schema"]
    # The schema is the tool's own input JSON Schema.
    assert schema["type"] == "object"
    assert "a" in schema["properties"]
    assert "b" in schema["properties"]


def test_operation_id_is_unique_and_python_safe() -> None:
    doc = _doc(add, greet)
    paths = doc["paths"]
    seen: set[str] = set()
    for item in paths.values():
        post = item["post"]
        op_id = post["operationId"]
        # OAS 3.1 requires operationId to be unique across all operations.
        assert isinstance(op_id, str)
        assert op_id not in seen
        seen.add(op_id)
        # Hyphens become underscores so the operationId is a valid Python
        # identifier — clients that auto-generate sync wrappers (httpx-codegen
        # etc.) require this.
        assert "-" not in op_id


def test_empty_tools_list_still_produces_valid_doc() -> None:
    doc = _doc()
    assert doc["openapi"] == "3.1.0"
    assert "info" in doc
    assert doc["paths"] == {}
