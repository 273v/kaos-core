from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from kaos_core import (
    ExecutionConfig,
    ExecutionEngine,
    ExecutionError,
    KaosResource,
    KaosRuntime,
    RegistryError,
    ResourceMetadata,
    ResourceRegistry,
    ResourceType,
    TaskDefinition,
    TaskError,
    TaskManager,
    TaskState,
    TextContent,
    ToolCapability,
    ToolCategory,
    ToolResult,
    WorkflowDefinition,
    WorkflowError,
    WorkflowExecutor,
    WorkflowStep,
    kaos_tool,
)
from kaos_core.execution.models import ExecutionResult
from kaos_core.types.content import EmbeddedResource
from kaos_core.types.enums import ExecutionState
from kaos_core.types.results import (
    ErrorInfo,
    ProgressResult,
    ProgressUpdate,
    StreamingChunk,
    StreamingResult,
)
from kaos_core.types.tasks import TaskListRequest


class MemoryResource(KaosResource):
    def __init__(
        self,
        uri: str,
        value: str,
        *,
        name: str = "Readme",
        description: str = "Project guide",
        tags: list[str] | None = None,
        provider_module: str = "kaos-core",
    ) -> None:
        super().__init__()
        self._metadata = ResourceMetadata(
            uri=uri,
            name=name,
            description=description,
            resource_type=ResourceType.DOCUMENT,
            tags=tags or ["guide"],
            provider_module=provider_module,
            version="0.1.0",
        )
        self.value = value
        self.read_count = 0

    @property
    def metadata(self) -> ResourceMetadata:
        return self._metadata

    async def read(self, context: Any = None) -> str:
        del context
        self.read_count += 1
        return self.value

    async def get_metadata(self, context: Any = None) -> dict[str, Any]:
        del context
        return {"read_count": self.read_count}


@kaos_tool(
    name="kaos-core-math-square",
    description="Square an integer",
    category=ToolCategory.DATA,
    capability=ToolCapability.TRANSFORM,
    module_name="kaos-core",
    version="0.1.0",
    tags=["math", "fast"],
    auto_register=False,
)
async def square(value: int) -> int:
    return value * value


@kaos_tool(
    name="kaos-core-text-trim",
    description="Trim whitespace from text",
    category=ToolCategory.TEXT,
    capability=ToolCapability.VALIDATE,
    module_name="kaos-core",
    version="0.1.0",
    tags=["text"],
    auto_register=False,
)
async def trim(text: str) -> str:
    return text.strip()


async def test_execution_engine_retry_failure_and_batch(runtime: Any) -> None:
    attempts = {"flaky": 0, "boom": 0}

    @kaos_tool(
        name="kaos-core-ops-flaky",
        description="Fail once, then succeed",
        category=ToolCategory.UTILITY,
        capability=ToolCapability.TRANSFORM,
        module_name="kaos-core",
        version="0.1.0",
        auto_register=False,
    )
    async def flaky(value: int) -> dict[str, int]:
        attempts["flaky"] += 1
        if attempts["flaky"] == 1:
            raise RuntimeError("transient")
        return {"value": value}

    @kaos_tool(
        name="kaos-core-ops-boom",
        description="Always fail",
        category=ToolCategory.UTILITY,
        capability=ToolCapability.TRANSFORM,
        module_name="kaos-core",
        version="0.1.0",
        auto_register=False,
    )
    async def boom() -> str:
        attempts["boom"] += 1
        raise RuntimeError("boom")

    runtime.tools.register_tool(flaky)
    runtime.tools.register_tool(boom)

    engine = ExecutionEngine(
        config=ExecutionConfig(max_retries=1, retry_delay=0.0, enable_caching=True),
        runtime=runtime,
    )

    with pytest.raises(ExecutionError):
        await engine.execute("kaos-core-ops-missing", {})

    success = await engine.execute("kaos-core-ops-flaky", {"value": 3})
    cached = await engine.execute("kaos-core-ops-flaky", {"value": 3})
    failed = await engine.execute("kaos-core-ops-boom", {})
    batch = await engine.execute_batch([("kaos-core-ops-flaky", {"value": 4}, None)])

    assert success.state == ExecutionState.COMPLETED
    assert success.retries == 1
    assert success.output is not None
    assert success.output.structuredContent == {"value": 3}
    assert cached.metadata["cached"] is True
    assert failed.state == ExecutionState.FAILED
    assert failed.error is not None
    assert "Function tool execution failed" in failed.error
    assert failed.retries == 1
    assert batch[0].output is not None
    assert batch[0].output.structuredContent == {"value": 4}
    assert engine.get_metrics("kaos-core-ops-flaky")["count"] == 2

    engine.clear_cache("kaos-core-ops-flaky")
    uncached = await engine.execute("kaos-core-ops-flaky", {"value": 3})
    assert uncached.metadata == {}

    engine.clear_cache()
    assert engine._cache == {}

    no_timeout_engine = ExecutionEngine(
        config=ExecutionConfig(timeout=None, enable_metrics=False),
        runtime=runtime,
    )
    direct = await no_timeout_engine.execute("kaos-core-ops-flaky", {"value": 8})
    assert direct.output is not None
    assert direct.output.structuredContent == {"value": 8}
    assert no_timeout_engine.get_metrics("unknown") == {"count": 0, "avg_duration": 0.0}
    assert no_timeout_engine.get_metrics() == {}


async def test_workflow_failure_modes() -> None:
    @kaos_tool(
        name="kaos-core-flow-error",
        description="Return an MCP error result",
        category=ToolCategory.UTILITY,
        capability=ToolCapability.VALIDATE,
        module_name="kaos-core",
        version="0.1.0",
        auto_register=False,
    )
    async def fail_step() -> ToolResult:
        return ToolResult.create_error("bad step")

    runtime = KaosRuntime()
    runtime.tools.register_tool(fail_step)
    engine = ExecutionEngine(runtime=runtime)
    executor = WorkflowExecutor(engine)
    executor.register_workflow(
        WorkflowDefinition(
            workflow_id="broken",
            name="Broken",
            steps=[WorkflowStep(step_id="fail", tool_name="kaos-core-flow-error")],
        )
    )

    result = await executor.execute_workflow("broken")
    assert result.success is False
    assert result.failed_step == "fail"
    assert result.steps[0].isError is True

    executor.register_workflow(
        WorkflowDefinition(
            workflow_id="cycle",
            name="Cycle",
            steps=[
                WorkflowStep(step_id="a", tool_name="kaos-core-flow-error", depends_on=["b"]),
                WorkflowStep(step_id="b", tool_name="kaos-core-flow-error", depends_on=["a"]),
            ],
        )
    )

    with pytest.raises(WorkflowError):
        await executor.execute_workflow("cycle")

    class NoOutputEngine(ExecutionEngine):
        async def execute(
            self,
            tool_name: str,
            inputs: dict[str, Any],
            context: Any = None,
            execution_id: str | None = None,
        ) -> ExecutionResult:
            del tool_name, inputs, context, execution_id
            return ExecutionResult(
                execution_id="missing-output",
                state=ExecutionState.FAILED,
                error="timed out",
            )

    empty_executor = WorkflowExecutor(NoOutputEngine(runtime=KaosRuntime()))
    empty_executor.register_workflow(
        WorkflowDefinition(
            workflow_id="empty",
            name="Empty",
            steps=[WorkflowStep(step_id="missing", tool_name="kaos-core-flow-void")],
        )
    )

    with pytest.raises(WorkflowError, match="timed out"):
        await empty_executor.execute_workflow("empty")


async def test_resource_registry_cache_search_and_templates() -> None:
    registry = ResourceRegistry()
    resource = MemoryResource("kaos://kaos-core/docs/readme", "hello")
    registry.register_resource(resource, templates=["kaos://kaos-core/docs/{name}"])

    with pytest.raises(RegistryError):
        registry.register_resource(resource)

    assert await registry.get_resource(resource.metadata.uri) == "hello"
    assert await registry.get_resource(resource.metadata.uri) == "hello"
    assert resource.read_count == 1

    registry.clear_cache(resource.metadata.uri)
    assert await registry.get_resource(resource.metadata.uri) == "hello"
    assert resource.read_count == 2

    matches = registry.search_resources(
        resource_type=ResourceType.DOCUMENT,
        module="kaos-core",
        tags=["guide"],
        query="readme",
    )
    assert matches == [resource.metadata]
    assert registry.list_templates() == ["kaos://kaos-core/docs/{name}"]
    assert (
        registry.resolve_template("kaos://kaos-core/docs/{name}", name="readme")
        == resource.metadata.uri
    )
    assert (
        registry.resolve_template("kaos://kaos-core/pages/{slug}", slug="intro")
        == "kaos://kaos-core/pages/intro"
    )
    assert registry.get_stats() == {"resources": 1, "templates": 1, "cached_entries": 1}

    registry.clear_cache()
    assert registry.get_stats()["cached_entries"] == 0

    with pytest.raises(RegistryError):
        await registry.get_resource("kaos://kaos-core/docs/missing")


def test_tool_registry_search_aliases_and_compatibility(runtime: Any) -> None:
    registry = runtime.tools
    registry.register_tool(square, aliases=["square"])
    registry.register_tool(trim)

    with pytest.raises(RegistryError):
        registry.register_tool(square)

    assert registry.get_tool("square") is square
    assert registry.get_tool_schema("square") == square.get_json_schema()
    assert registry.get_tool_schema("missing") is None
    assert registry.search_tools(category=ToolCategory.DATA) == [square.metadata]
    assert registry.search_tools(capability=ToolCapability.VALIDATE) == [trim.metadata]
    assert registry.search_tools(tags=["math"], query="square", namespace="kaos-core") == [
        square.metadata
    ]
    assert registry.find_compatible_tools(input_type="integer", output_type="integer") == [
        "kaos-core-math-square"
    ]
    assert registry.find_compatible_tools(input_type="string", output_type="string") == [
        "kaos-core-text-trim"
    ]
    assert registry.get_tool_hierarchy() == {
        "kaos-core": ["kaos-core-math-square", "kaos-core-text-trim"],
    }
    assert registry.list_tools() == ["kaos-core-math-square", "kaos-core-text-trim"]
    assert registry.get_tools(["square", "missing"]) == {"square": square}
    assert registry.get_stats() == {"tools": 2, "aliases": 1}
    assert len(registry.list_tool_objects()) == 2

    namespace = runtime.namespaces.get_namespace_info("kaos-core")
    assert namespace is not None
    assert namespace.tool_count == 2
    assert runtime.namespaces.resolve_name("square") == "kaos-core-math-square"


async def test_task_manager_failure_cancellation_and_pagination() -> None:
    disabled = TaskManager(enabled=False)
    with pytest.raises(TaskError):
        await disabled.create_task(
            TaskDefinition(task_id="disabled", name="Disabled", tool_name="noop")
        )

    started = asyncio.Event()
    release = asyncio.Event()

    async def sleeping_executor(definition: TaskDefinition) -> ToolResult:
        del definition
        started.set()
        await release.wait()
        return ToolResult.create_text("done")

    manager = TaskManager(executor=sleeping_executor, enabled=True)
    await manager.create_task(TaskDefinition(task_id="cancel-me", name="Cancel", tool_name="noop"))
    await started.wait()

    with pytest.raises(TaskError):
        await manager.get_task_result("cancel-me")

    assert await manager.cancel_task("cancel-me") is True
    with pytest.raises(asyncio.CancelledError):
        await manager.wait_for_task("cancel-me", timeout=1.0)

    cancelled = await manager.get_task("cancel-me")
    assert cancelled.state == TaskState.CANCELLED
    assert cancelled.message == "cancelled"
    assert await manager.cancel_task("missing") is False

    with pytest.raises(TaskError):
        await manager.get_task("missing")

    async def failing_executor(definition: TaskDefinition) -> ToolResult:
        del definition
        raise RuntimeError("task exploded")

    failing_manager = TaskManager(executor=failing_executor, enabled=True)
    await failing_manager.create_task(
        TaskDefinition(task_id="failed", name="Failed", tool_name="noop")
    )
    failed = await failing_manager.wait_for_task("failed", timeout=1.0)
    assert failed.state == TaskState.FAILED
    assert failed.result is not None
    assert failed.result.isError is True
    assert failed.result.content[0] == TextContent(text="task exploded")
    blocking_result = await failing_manager.get_task_result("failed", blocking=True)
    assert blocking_result.isError is True

    paged_manager = TaskManager(enabled=True)
    for index in range(51):
        await paged_manager.create_task(
            TaskDefinition(task_id=f"task-{index}", name=f"Task {index}", tool_name="noop")
        )

    first_page = await paged_manager.list_tasks(TaskListRequest())
    assert len(first_page.tasks) == 50
    assert first_page.next_cursor == "50"
    second_page = await paged_manager.list_tasks(TaskListRequest(cursor="50"))
    assert len(second_page.tasks) == 1
    assert second_page.next_cursor is None


async def test_result_helpers_and_progress_flows() -> None:
    success_text = ToolResult.create_success("ok")
    success_structured = ToolResult.create_success({"value": 4})
    success_content = ToolResult.create_success(content=[TextContent(text="named")])
    error = ToolResult.create_error(
        ErrorInfo(code="bad_request", message="nope", details={"field": "value"}),
        _meta={"request_id": "req-1"},
    )
    resource_link = ToolResult.create_resource_link(
        "kaos://kaos-core/docs/readme",
        name="Readme",
        mime_type="text/plain",
    )

    assert success_text.content[0] == TextContent(text="ok")
    assert success_structured.structuredContent == {"value": 4}
    assert success_content.content[0] == TextContent(text="named")
    assert error.isError is True
    assert error._meta == {
        "request_id": "req-1",
        "error": {
            "code": "bad_request",
            "message": "nope",
            "details": {"field": "value"},
        },
    }
    embedded = resource_link.content[0]
    assert isinstance(embedded, EmbeddedResource)
    assert embedded.resource["uri"] == "kaos://kaos-core/docs/readme"
    assert ToolResult.create_text("plain").to_mcp_dict()["content"][0]["text"] == "plain"

    async def iterate_chunks() -> AsyncIterator[StreamingChunk]:
        yield StreamingChunk(data="first", index=0)
        yield StreamingChunk(data="final", index=1, is_final=True)

    streaming = StreamingResult(iterate_chunks())
    chunks = [chunk async for chunk in streaming.chunks()]
    assert chunks[-1].is_final is True

    collected = await StreamingResult(iterate_chunks()).collect()
    assert collected == ["first", "final"]

    progress = ProgressResult()
    await progress.publish(ProgressUpdate.from_current(1, total=4, message="warming"))
    await progress.finish(ToolResult.create_text("done"))
    updates = [update async for update in progress.progress()]
    assert updates[0].percentage == 25.0
    completed = await progress.wait_for_completion()
    assert completed is not None
    assert completed.content[0] == TextContent(text="done")

    unfinished = ProgressResult()
    await unfinished.finish()
    assert await unfinished.wait_for_completion() is None
