from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kaos_core import (
    ElicitationMode,
    ElicitationRequest,
    TaskDefinition,
    TaskManager,
    URLElicitationRequiredError,
    VFSFile,
)
from kaos_core.types import TaskListRequest
from kaos_core.types.enums import StorageBackend, TaskState
from kaos_core.vfs.core import VirtualFileSystem
from kaos_core.vfs.models import VFSConfig


def test_elicitation_rejects_sensitive_form_schema() -> None:
    with pytest.raises(URLElicitationRequiredError):
        ElicitationRequest(
            elicitation_id="1",
            message="Need credentials",
            mode=ElicitationMode.FORM,
            requested_schema={"properties": {"api_key": {"type": "string"}}},
        )


async def test_task_manager_pagination_and_cleanup() -> None:
    manager = TaskManager(enabled=True)
    await manager.create_task(TaskDefinition(task_id="one", name="One", tool_name="tool", ttl=0.1))
    await manager.create_task(TaskDefinition(task_id="two", name="Two", tool_name="tool"))

    manager._statuses["one"] = manager._statuses["one"].model_copy(
        update={"updated_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}
    )

    page = await manager.list_tasks(TaskListRequest(state_filter=TaskState.WORKING))
    assert len(page.tasks) == 2
    assert await manager.cleanup_expired() == 1


async def test_disk_vfs_and_file_wrapper(tmp_path: Path) -> None:
    vfs = VirtualFileSystem(VFSConfig(default_backend=StorageBackend.DISK, disk_base_path=tmp_path))
    path = vfs.get_path("logs/output.txt", context_id="ctx")
    await path.write_text("hello")

    assert await path.exists() is True
    assert await path.read_text() == "hello"
    assert await path.parent.is_dir() is True
    children = await path.parent.iterdir()
    assert len(children) == 1
    assert await children[0].exists() is True
    assert await children[0].read_text() == "hello"

    raw = VFSFile(b"abc")
    assert raw.read() == b"abc"
