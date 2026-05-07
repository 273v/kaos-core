from __future__ import annotations

from pydantic import Field

from kaos_core.types.content import KaosModel
from kaos_core.types.results import ToolResult


class UsageStats(KaosModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class DelegationRequest(KaosModel):
    target_agent: str
    prompt: str
    inputs: dict[str, object] = Field(default_factory=dict)
    context_forward: bool = True
    usage_tracking: bool = True


class DelegationResult(KaosModel):
    agent: str
    result: ToolResult
    usage: UsageStats = Field(default_factory=UsageStats)
