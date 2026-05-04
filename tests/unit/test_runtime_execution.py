from __future__ import annotations

from typing import Any, cast

import pytest

from kaos_core import (
    ExecutionConfig,
    ExecutionEngine,
    ToolCapability,
    ToolCategory,
    WorkflowDefinition,
    WorkflowError,
    WorkflowExecutor,
    WorkflowStep,
    kaos_tool,
)


@kaos_tool(
    name="kaos-core-math-double",
    description="Double a number",
    category=ToolCategory.DATA,
    capability=ToolCapability.TRANSFORM,
    module_name="kaos-core",
    version="0.1.0",
    auto_register=False,
)
async def double(value: int) -> dict[str, int]:
    return {"value": value * 2}


@kaos_tool(
    name="kaos-core-math-summarize",
    description="Summarize dependency results",
    category=ToolCategory.DATA,
    capability=ToolCapability.ANALYZE,
    module_name="kaos-core",
    version="0.1.0",
    auto_register=False,
)
async def summarize(dependencies: dict[str, dict[str, object]]) -> dict[str, int]:
    payload = cast(dict[str, Any], dependencies["double"])
    structured = cast(dict[str, int], payload["structuredContent"])
    first = structured["value"]
    return {"summary": int(first) + 1}


@kaos_tool(
    name="kaos-core-math-sleep",
    description="Sleep for a requested delay",
    category=ToolCategory.UTILITY,
    capability=ToolCapability.TRANSFORM,
    module_name="kaos-core",
    version="0.1.0",
    auto_register=False,
)
async def sleep_for(delay: float) -> str:
    import asyncio

    await asyncio.sleep(delay)
    return "done"


async def test_execution_engine_and_workflow(runtime: Any) -> None:
    runtime.tools.register_tool(double)
    runtime.tools.register_tool(summarize)
    runtime.tools.register_tool(sleep_for)
    engine = ExecutionEngine(config=ExecutionConfig(enable_caching=True), runtime=runtime)

    first = await engine.execute("kaos-core-math-double", {"value": 4})
    second = await engine.execute("kaos-core-math-double", {"value": 4})

    assert first.output is not None
    assert first.output.structuredContent == {"value": 8}
    assert second.metadata["cached"] is True

    workflow = WorkflowDefinition(
        workflow_id="incremental",
        name="Incremental Workflow",
        steps=[
            WorkflowStep(step_id="double", tool_name="kaos-core-math-double", inputs={"value": 3}),
            WorkflowStep(
                step_id="summarize",
                tool_name="kaos-core-math-summarize",
                depends_on=["double"],
            ),
        ],
    )
    executor = WorkflowExecutor(engine)
    executor.register_workflow(workflow)
    result = await executor.execute_workflow("incremental")

    assert result.success is True
    assert result.steps[-1].structuredContent == {"summary": 7}


async def test_workflow_uses_definition_config(runtime: Any) -> None:
    runtime.tools.register_tool(sleep_for)
    engine = ExecutionEngine(config=ExecutionConfig(timeout=1.0), runtime=runtime)
    workflow = WorkflowDefinition(
        workflow_id="timed",
        name="Timed Workflow",
        steps=[
            WorkflowStep(step_id="sleep", tool_name="kaos-core-math-sleep", inputs={"delay": 0.05})
        ],
        config=ExecutionConfig(timeout=0.0001),
    )

    executor = WorkflowExecutor(engine)
    executor.register_workflow(workflow)

    with pytest.raises(WorkflowError):
        await executor.execute_workflow("timed")
