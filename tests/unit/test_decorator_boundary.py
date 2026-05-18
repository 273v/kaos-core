from __future__ import annotations

from typing import Any

from kaos_core import KaosRuntime, ToolAnnotations, ToolCapability, ToolCategory, kaos_tool


def test_decorator_defaults_to_explicit_registration(runtime: KaosRuntime) -> None:
    @kaos_tool(
        name="kaos-test-explicit-registration",
        description="Return a fixed value",
        category=ToolCategory.DATA,
        capability=ToolCapability.QUERY,
    )
    async def decorated_tool() -> str:
        return "ok"

    assert runtime.tools.get_tool("kaos-test-explicit-registration") is None
    assert decorated_tool.metadata.annotations == ToolAnnotations()


def test_decorator_auto_register_still_opt_in(runtime: KaosRuntime) -> None:
    @kaos_tool(
        name="kaos-test-auto-registration",
        description="Return a fixed value",
        category=ToolCategory.DATA,
        capability=ToolCapability.QUERY,
        auto_register=True,
    )
    async def decorated_tool() -> str:
        return "ok"

    assert runtime.tools.get_tool("kaos-test-auto-registration") is decorated_tool


async def test_function_tool_returns_structured_output_with_summary() -> None:
    @kaos_tool(
        name="kaos-test-structured-summary",
        description="Return structured data",
        category=ToolCategory.DATA,
        capability=ToolCapability.QUERY,
    )
    async def decorated_tool() -> dict[str, Any]:
        return {"value": 7}

    result = await decorated_tool.execute({})

    assert not result.isError
    assert result.structuredContent == {"value": 7}
    assert result.text == (
        "kaos-test-structured-summary returned structured data with 1 field: value."
    )
    assert decorated_tool.metadata.output_schema == {"type": "object"}


async def test_function_tool_converts_function_exception_to_error_result() -> None:
    sentinel = "sk-secret-should-not-leak"

    @kaos_tool(
        name="kaos-test-function-error",
        description="Raise from wrapped function",
        category=ToolCategory.DATA,
        capability=ToolCapability.QUERY,
    )
    async def decorated_tool() -> str:
        raise RuntimeError(f"backend unavailable: {sentinel}")

    result = await decorated_tool.execute({})

    assert result.isError
    assert result.text is not None
    assert "kaos-test-function-error failed during execution" in result.text
    assert sentinel not in result.text
    assert sentinel not in result.model_dump_json()
    assert result.meta is not None
    error = result.meta["error"]
    assert error["code"] == "function_tool_execution_failed"
    assert error["details"]["exception_type"] == "RuntimeError"
    assert "exception" not in error["details"]
