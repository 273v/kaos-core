from __future__ import annotations

from enum import StrEnum
from typing import Any

from kaos_core.types.content import KaosModel


class McpLogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    ALERT = "alert"
    EMERGENCY = "emergency"


class LogEvent(KaosModel):
    level: McpLogLevel
    logger: str | None = None
    data: Any
