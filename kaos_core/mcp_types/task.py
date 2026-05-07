from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from kaos_core.exceptions import TaskError
from kaos_core.mcp_types.settings import AgentSettings
from kaos_core.types.enums import TaskState
from kaos_core.types.results import ToolResult
from kaos_core.types.tasks import (
    CreateTaskResult,
    TaskDefinition,
    TaskListRequest,
    TaskListResponse,
    TaskStatus,
)

TaskExecutor = Callable[[TaskDefinition], Awaitable[ToolResult]]


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


class TaskManager:
    def __init__(
        self,
        executor: TaskExecutor | None = None,
        *,
        enabled: bool = False,
        settings: AgentSettings | None = None,
    ) -> None:
        self._executor = executor
        self._enabled = enabled
        self._settings = settings or AgentSettings()
        self._statuses: dict[str, TaskStatus] = {}
        self._definitions: dict[str, TaskDefinition] = {}
        self._handles: dict[str, asyncio.Task[None]] = {}

    def is_enabled(self) -> bool:
        return self._enabled

    async def create_task(self, definition: TaskDefinition) -> CreateTaskResult:
        if not self._enabled:
            raise TaskError("Task manager is disabled", task_id=definition.task_id)
        created_at = _iso_now()
        self._definitions[definition.task_id] = definition
        self._statuses[definition.task_id] = TaskStatus(
            task_id=definition.task_id,
            state=TaskState.WORKING,
            created_at=created_at,
            updated_at=created_at,
            poll_interval=self._settings.poll_interval,
        )
        if self._executor is not None:
            self._handles[definition.task_id] = asyncio.create_task(self._run(definition))
        # `meta` is a pydantic alias for `_meta` (populate_by_name=True);
        # ty does not yet read pydantic config, so the kwarg is reported
        # as unknown even though it is accepted at runtime.
        return CreateTaskResult(
            task_id=definition.task_id,
            meta={"io.modelcontextprotocol/related-task": definition.task_id},  # ty: ignore[unknown-argument]
        )

    async def _run(self, definition: TaskDefinition) -> None:
        assert self._executor is not None
        try:
            result = await self._executor(definition)
        except asyncio.CancelledError:
            self._set_status(definition.task_id, TaskState.CANCELLED, message="cancelled")
            raise
        except Exception as exc:
            self._set_status(
                definition.task_id,
                TaskState.FAILED,
                message=str(exc),
                result=ToolResult.create_error(str(exc)),
            )
        else:
            self._set_status(definition.task_id, TaskState.COMPLETED, result=result)

    def _set_status(
        self,
        task_id: str,
        state: TaskState,
        *,
        message: str | None = None,
        result: ToolResult | None = None,
    ) -> None:
        current = self._statuses[task_id]
        self._statuses[task_id] = current.model_copy(
            update={
                "state": state,
                "message": message,
                "result": result,
                "updated_at": _iso_now(),
            }
        )

    async def get_task(self, task_id: str) -> TaskStatus:
        try:
            return self._statuses[task_id]
        except KeyError as exc:
            raise TaskError("Unknown task", task_id=task_id) from exc

    async def get_task_result(self, task_id: str, blocking: bool = False) -> ToolResult:
        if blocking:
            await self.wait_for_task(task_id)
        status = await self.get_task(task_id)
        if status.result is None:
            raise TaskError("Task result is not ready", task_id=task_id)
        return status.result

    async def cancel_task(self, task_id: str) -> bool:
        handle = self._handles.get(task_id)
        if handle is None:
            return False
        handle.cancel()
        return True

    async def list_tasks(self, request: TaskListRequest) -> TaskListResponse:
        statuses = list(self._statuses.values())
        if request.state_filter is not None:
            statuses = [status for status in statuses if status.state == request.state_filter]
        start = int(request.cursor or "0")
        page_size = self._settings.task_page_size
        page = statuses[start : start + page_size]
        next_cursor = str(start + page_size) if start + page_size < len(statuses) else None
        return TaskListResponse(tasks=page, next_cursor=next_cursor)

    async def wait_for_task(self, task_id: str, timeout: float | None = None) -> TaskStatus:
        handle = self._handles.get(task_id)
        if handle is not None:
            await asyncio.wait_for(asyncio.shield(handle), timeout=timeout)
        return await self.get_task(task_id)

    async def cleanup_expired(self) -> int:
        removed = 0
        now = datetime.now(UTC)
        for task_id, definition in list(self._definitions.items()):
            if definition.ttl is None:
                continue
            status = self._statuses[task_id]
            updated_at = datetime.fromisoformat(status.updated_at)
            if (now - updated_at).total_seconds() > definition.ttl:
                self._definitions.pop(task_id, None)
                self._statuses.pop(task_id, None)
                handle = self._handles.pop(task_id, None)
                if handle is not None:
                    handle.cancel()
                removed += 1
        return removed
