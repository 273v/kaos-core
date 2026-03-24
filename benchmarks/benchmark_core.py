from __future__ import annotations

import asyncio
import statistics
import time

from kaos_core import (
    ExecutionConfig,
    ExecutionEngine,
    KaosRuntime,
    ToolCapability,
    ToolCategory,
    kaos_tool,
)


@kaos_tool(
    name="kaos-core-bench-add",
    description="Add two integers",
    category=ToolCategory.DATA,
    capability=ToolCapability.TRANSFORM,
    module_name="kaos-core",
    version="0.1.0",
    auto_register=False,
)
async def add(left: int, right: int) -> dict[str, int]:
    return {"total": left + right}


async def benchmark() -> None:
    runtime = KaosRuntime()
    runtime.tools.register_tool(add)
    uncached_engine = ExecutionEngine(
        runtime=runtime,
        config=ExecutionConfig(enable_caching=False, enable_metrics=False),
    )
    cached_engine = ExecutionEngine(
        runtime=runtime,
        config=ExecutionConfig(enable_caching=True, enable_metrics=False),
    )

    lookup_samples: list[float] = []
    uncached_execute_samples: list[float] = []
    cached_execute_samples: list[float] = []

    for _ in range(500):
        start = time.perf_counter()
        runtime.tools.get_tool("kaos-core-bench-add")
        lookup_samples.append((time.perf_counter() - start) * 1_000_000)

    for _ in range(200):
        start = time.perf_counter()
        await uncached_engine.execute("kaos-core-bench-add", {"left": 2, "right": 3})
        uncached_execute_samples.append((time.perf_counter() - start) * 1_000_000)

    await cached_engine.execute("kaos-core-bench-add", {"left": 2, "right": 3})
    for _ in range(200):
        start = time.perf_counter()
        await cached_engine.execute("kaos-core-bench-add", {"left": 2, "right": 3})
        cached_execute_samples.append((time.perf_counter() - start) * 1_000_000)

    def p95(values: list[float]) -> float:
        return statistics.quantiles(values, n=20, method="inclusive")[18]

    print(f"Registry lookup mean: {statistics.mean(lookup_samples):.2f} us")
    print(f"Registry lookup p95: {p95(lookup_samples):.2f} us")
    print(f"Execution mean (uncached): {statistics.mean(uncached_execute_samples):.2f} us")
    print(f"Execution p95 (uncached): {p95(uncached_execute_samples):.2f} us")
    print(f"Execution mean (cached): {statistics.mean(cached_execute_samples):.2f} us")
    print(f"Execution p95 (cached): {p95(cached_execute_samples):.2f} us")


if __name__ == "__main__":
    asyncio.run(benchmark())
