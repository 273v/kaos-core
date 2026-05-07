"""MCP wire-protocol types for sampling, elicitation, and async tasks.

These models match the MCP specification's client-initiated subaction
shapes one-to-one. They live in ``kaos-core`` (not ``kaos-mcp``) because
``kaos-core`` is the platform's MCP-native type foundation: every other
``kaos-*`` package consumes these types, and forcing them through
``kaos-mcp`` would create the wrong dependency direction.

Renamed from ``kaos_core.agent`` at v0.1.0a3 — the previous name
collided with ``kaos-agents`` (the agent runtime), but the contents
have always been MCP protocol shapes, not agent-runtime primitives.

Note: ``DelegationRequest`` / ``DelegationResult`` / ``UsageStats``
moved to :mod:`kaos_core.types.delegation` because they describe an
A2A pattern that is not part of the MCP spec.
"""

from kaos_core.mcp_types.elicitation import (
    ElicitationCompletionNotification,
    ElicitationRequest,
    ElicitationResponse,
)
from kaos_core.mcp_types.sampling import (
    ModelHint,
    ModelPreferences,
    SamplingRequest,
    SamplingResponse,
)
from kaos_core.mcp_types.settings import AgentSettings
from kaos_core.mcp_types.task import TaskManager

__all__ = [
    "AgentSettings",
    "ElicitationCompletionNotification",
    "ElicitationRequest",
    "ElicitationResponse",
    "ModelHint",
    "ModelPreferences",
    "SamplingRequest",
    "SamplingResponse",
    "TaskManager",
]
