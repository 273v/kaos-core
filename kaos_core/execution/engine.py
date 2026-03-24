from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import Any
from uuid import uuid4

from kaos_core.base.context import KaosContext
from kaos_core.exceptions import ExecutionError
from kaos_core.execution.models import ExecutionConfig, ExecutionResult
from kaos_core.logging import get_logger
from kaos_core.registry.container import KaosRuntime
from kaos_core.types.enums import ExecutionState
from kaos_core.types.results import ToolResult


class ExecutionEngine:
    def __init__(
        self, config: ExecutionConfig | None = None, runtime: KaosRuntime | None = None
    ) -> None:
        self.config = config or ExecutionConfig()
        self.runtime = runtime or KaosRuntime.default()
        self._cache: dict[str, ToolResult] = {}
        self._metrics: dict[str, list[float]] = defaultdict(list)
        self._semaphore = asyncio.Semaphore(self.config.parallel_limit)
        self._logger = get_logger("kaos.execution")

    async def execute(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        context: KaosContext | None = None,
        execution_id: str | None = None,
    ) -> ExecutionResult:
        tool = self.runtime.tools.get_tool(tool_name)
        if tool is None:
            raise ExecutionError("Tool not found", tool_name=tool_name)
        cache_key = self._cache_key(tool_name, inputs)
        if self.config.enable_caching and cache_key in self._cache:
            return ExecutionResult(
                execution_id=execution_id or str(uuid4()),
                state=ExecutionState.COMPLETED,
                output=self._cache[cache_key],
                metadata={"cached": True},
            )

        attempt = 0
        start = time.perf_counter()
        async with self._semaphore:
            while True:
                try:
                    result = await self._execute_once(tool_name, inputs, context=context)
                except Exception as exc:
                    if attempt >= self.config.max_retries:
                        duration = time.perf_counter() - start
                        return ExecutionResult(
                            execution_id=execution_id or str(uuid4()),
                            state=ExecutionState.FAILED,
                            error=str(exc),
                            duration=duration,
                            retries=attempt,
                        )
                    attempt += 1
                    if self.config.retry_delay:
                        await asyncio.sleep(self.config.retry_delay)
                    continue
                duration = time.perf_counter() - start
                if self.config.enable_metrics:
                    self._metrics[tool_name].append(duration)
                if self.config.enable_caching:
                    self._cache[cache_key] = result
                return ExecutionResult(
                    execution_id=execution_id or str(uuid4()),
                    state=ExecutionState.COMPLETED,
                    output=result,
                    duration=duration,
                    retries=attempt,
                )

    async def _execute_once(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        context: KaosContext | None = None,
    ) -> ToolResult:
        tool = self.runtime.tools.get_tool(tool_name)
        if tool is None:
            raise ExecutionError("Tool not found", tool_name=tool_name)
        call_context = context or KaosContext.create(runtime=self.runtime)
        if self.config.timeout is None:
            return await tool.execute(inputs, context=call_context)
        return await asyncio.wait_for(
            tool.execute(inputs, context=call_context), timeout=self.config.timeout
        )

    async def execute_batch(
        self,
        requests: list[tuple[str, dict[str, Any], KaosContext | None]],
    ) -> list[ExecutionResult]:
        return await asyncio.gather(
            *[
                self.execute(tool_name, inputs, context=context)
                for tool_name, inputs, context in requests
            ]
        )

    def get_metrics(self, tool_name: str | None = None) -> dict[str, Any]:
        if tool_name is not None:
            timings = self._metrics.get(tool_name, [])
            return {
                "count": len(timings),
                "avg_duration": (sum(timings) / len(timings)) if timings else 0.0,
            }
        return {
            name: {"count": len(timings), "avg_duration": sum(timings) / len(timings)}
            for name, timings in self._metrics.items()
            if timings
        }

    def clear_cache(self, tool_name: str | None = None) -> None:
        if tool_name is None:
            self._cache.clear()
            return
        prefix = f"{tool_name}:"
        for key in [cache_key for cache_key in self._cache if cache_key.startswith(prefix)]:
            self._cache.pop(key, None)

    def _cache_key(self, tool_name: str, inputs: dict[str, Any]) -> str:
        return f"{tool_name}:{json.dumps(inputs, sort_keys=True, default=str)}"
