from __future__ import annotations

import json
import logging


class ContextFilter(logging.Filter):
    def __init__(self, session_id: str | None = None, trace_id: str | None = None) -> None:
        super().__init__()
        self.session_id = session_id
        self.trace_id = trace_id

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "session_id"):
            record.session_id = self.session_id or "-"
        if not hasattr(record, "trace_id"):
            record.trace_id = self.trace_id or "-"
        return True


class StructuredFormatter(logging.Formatter):
    def __init__(self, *, json_output: bool = False) -> None:
        super().__init__()
        self.json_output = json_output

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "session_id": getattr(record, "session_id", "-"),
            "trace_id": getattr(record, "trace_id", "-"),
        }
        if self.json_output:
            return json.dumps(payload, sort_keys=True)
        return (
            f"{payload['level']} {payload['logger']} "
            f"[session={payload['session_id']} trace={payload['trace_id']}] "
            f"{payload['message']}"
        )


def setup_kaos_logging(
    *,
    log_level: str = "INFO",
    log_format: str = "text",
    log_file: str | None = None,
    force: bool = False,
) -> logging.Logger:
    logger = logging.getLogger("kaos")
    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)
    formatter = StructuredFormatter(json_output=log_format.lower() == "json")
    handler: logging.Handler = (
        logging.FileHandler(log_file) if log_file else logging.StreamHandler()
    )
    handler.setFormatter(formatter)
    if force:
        logger.handlers.clear()
    if not logger.handlers:
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers and not logging.getLogger("kaos").handlers:
        setup_kaos_logging()
    return logger
