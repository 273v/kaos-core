from __future__ import annotations

import time
from typing import Any

from kaos_core.base.context import KaosContext
from kaos_core.exceptions import WorkflowError
from kaos_core.execution.engine import ExecutionEngine
from kaos_core.execution.models import WorkflowDefinition
from kaos_core.types.results import ToolResult, WorkflowResult


class WorkflowExecutor:
    def __init__(self, engine: ExecutionEngine | None = None) -> None:
        self.engine = engine or ExecutionEngine()
        self._workflows: dict[str, WorkflowDefinition] = {}

    def register_workflow(self, workflow: WorkflowDefinition) -> None:
        self._workflows[workflow.workflow_id] = workflow

    def get_registered_workflows(self) -> list[str]:
        return sorted(self._workflows)

    async def execute_workflow(
        self,
        workflow_id: str,
        inputs: dict[str, Any] | None = None,
        context: KaosContext | None = None,
    ) -> WorkflowResult:
        try:
            workflow = self._workflows[workflow_id]
        except KeyError as exc:
            raise WorkflowError("Workflow not found", workflow_id=workflow_id) from exc
        provided_inputs = inputs or {}
        results: dict[str, ToolResult] = {}
        ordered_steps = self._resolve(workflow)
        engine = self._engine_for_workflow(workflow)
        start = time.perf_counter()
        for step in ordered_steps:
            step_inputs = {**workflow.inputs, **step.inputs, **provided_inputs}
            if step.depends_on:
                step_inputs["dependencies"] = {
                    dependency: results[dependency].model_dump(by_alias=True, exclude_none=True)
                    for dependency in step.depends_on
                }
            execution_result = await engine.execute(step.tool_name, step_inputs, context=context)
            if execution_result.output is None:
                raise WorkflowError(
                    "Workflow step produced no output",
                    step_id=step.step_id,
                    error=execution_result.error,
                )
            results[step.step_id] = execution_result.output
            if execution_result.output.isError:
                return WorkflowResult(
                    success=False,
                    steps=list(results.values()),
                    execution_time=time.perf_counter() - start,
                    failed_step=step.step_id,
                )
        return WorkflowResult(
            success=True,
            steps=list(results.values()),
            execution_time=time.perf_counter() - start,
        )

    def _resolve(self, workflow: WorkflowDefinition) -> list[Any]:
        resolved: list[Any] = []
        resolved_ids: set[str] = set()
        remaining = {step.step_id: step for step in workflow.steps}
        while remaining:
            ready = [
                step for step in remaining.values() if set(step.depends_on).issubset(resolved_ids)
            ]
            if not ready:
                raise WorkflowError(
                    "Workflow contains a dependency cycle", workflow_id=workflow.workflow_id
                )
            for step in ready:
                resolved.append(step)
                resolved_ids.add(step.step_id)
                remaining.pop(step.step_id, None)
        return resolved

    def _engine_for_workflow(self, workflow: WorkflowDefinition) -> ExecutionEngine:
        overrides = workflow.config.model_dump(exclude_unset=True)
        if not overrides:
            return self.engine
        return ExecutionEngine(
            config=self.engine.config.model_copy(update=overrides),
            runtime=self.engine.runtime,
        )
