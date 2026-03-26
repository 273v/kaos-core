from __future__ import annotations

from typing import Any

from pydantic import Field

from kaos_core.types.aliases import Cursor
from kaos_core.types.content import KaosModel
from kaos_core.types.enums import TaskState
from kaos_core.types.results import ToolResult


class TaskDefinition(KaosModel):
    task_id: str
    name: str
    description: str | None = None
    tool_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    timeout: float | None = Field(default=None, gt=0.0)
    ttl: float | None = Field(default=None, gt=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateTaskResult(KaosModel):
    task_id: str
    meta: dict[str, Any] | None = Field(default=None, alias="_meta")


class TaskStatus(KaosModel):
    task_id: str
    state: TaskState
    progress: float | None = None
    message: str | None = None
    poll_interval: float | None = Field(default=None, ge=0.0)
    result: ToolResult | None = None
    created_at: str
    updated_at: str


class TaskListRequest(KaosModel):
    cursor: Cursor | None = None
    state_filter: TaskState | None = None


class TaskListResponse(KaosModel):
    tasks: list[TaskStatus]
    next_cursor: Cursor | None = None
