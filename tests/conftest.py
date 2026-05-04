from __future__ import annotations

from pathlib import Path

import pytest

from kaos_core.registry import KaosRuntime


@pytest.fixture()
def runtime(tmp_path: Path) -> KaosRuntime:
    runtime = KaosRuntime()
    runtime.vfs.config.disk_base_path = tmp_path / "vfs"
    KaosRuntime.set_default(runtime)
    return runtime
