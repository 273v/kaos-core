from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from kaos_core.registry import KaosRuntime


@pytest.fixture()
def runtime(tmp_path: Path) -> Iterator[KaosRuntime]:
    runtime = KaosRuntime()
    runtime.vfs.config.disk_base_path = tmp_path / "vfs"
    token = KaosRuntime.set_default(runtime)
    try:
        yield runtime
    finally:
        KaosRuntime.reset_default(token)
