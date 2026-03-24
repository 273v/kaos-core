from __future__ import annotations

from typing import Any

from pydantic import Field

from kaos_core.types.content import KaosModel
from kaos_core.types.enums import ExecutionState
from kaos_core.types.results import ToolResult


class ExecutionConfig(KaosModel):
    max_retries: int = Field(default=0, ge=0)
    retry_delay: float = Field(default=0.0, ge=0.0)
    timeout: float | None = Field(default=30.0, gt=0.0)
    parallel_limit: int = Field(default=8, ge=1)
    enable_caching: bool = True
    enable_logging: bool = True
    enable_metrics: bool = True


class ExecutionContext(KaosModel):
    execution_id: str
    tool_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(KaosModel):
    execution_id: str
    state: ExecutionState
    output: ToolResult | None = None
    error: str | None = None
    duration: float = 0.0
    retries: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowStep(KaosModel):
    step_id: str
    tool_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class WorkflowDefinition(KaosModel):
    workflow_id: str
    name: str
    description: str | None = None
    steps: list[WorkflowStep]
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    config: ExecutionConfig = Field(default_factory=ExecutionConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)
