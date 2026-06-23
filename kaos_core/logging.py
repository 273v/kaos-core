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
        # Drop any prior handlers (including the default NullHandler) so the
        # application's configuration fully replaces it.
        logger.handlers.clear()
    # Only attach our handler if the logger has no *real* handler yet. The
    # library installs a NullHandler by default (see ``_install_null_handler``);
    # treat that as "unconfigured" and replace it.
    real_handlers = [h for h in logger.handlers if not isinstance(h, logging.NullHandler)]
    if not real_handlers:
        for null in [h for h in logger.handlers if isinstance(h, logging.NullHandler)]:
            logger.removeHandler(null)
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def _install_null_handler() -> None:
    """Attach a single :class:`logging.NullHandler` to the ``kaos`` logger.

    This follows the standard library convention for libraries: it keeps the
    library silent by default and prevents "No handlers could be found"
    warnings, while leaving handler/level/format configuration entirely to the
    application (via :func:`setup_kaos_logging`). The library must never attach
    a real handler or set a level as a side effect of import or operation.
    """
    root = logging.getLogger("kaos")
    if not any(isinstance(h, logging.NullHandler) for h in root.handlers):
        root.addHandler(logging.NullHandler())


# Install the NullHandler as soon as this module is imported so the ``kaos``
# logger hierarchy is silent by default and never emits the stdlib
# "No handlers could be found" warning. This is the one library-side logging
# action that the convention explicitly permits; it attaches no real handler,
# sets no level, and does not touch ``propagate``.
_install_null_handler()


def get_logger(name: str) -> logging.Logger:
    """Get a logger under the ``kaos`` hierarchy.

    Names are automatically mapped so that loggers inherit handlers and
    filters from the ``kaos`` root logger:

    * ``kaos.context`` → unchanged (already in hierarchy)
    * ``kaos_web.clients.http`` → ``kaos.web.clients.http``
    * ``my_module`` → ``kaos.my_module``

    This means ``get_logger(__name__)`` in any kaos package produces a
    logger that inherits the structured formatter and context filter.
    """
    if not name.startswith("kaos"):
        name = f"kaos.{name}"
    elif name.startswith("kaos_"):
        # kaos_web.clients.http → kaos.web.clients.http
        name = "kaos." + name[5:]
    # else: already starts with "kaos." — use as-is

    # NOTE: A library must never auto-configure logging (attach real handlers,
    # set levels, or call basicConfig) as a side effect of obtaining a logger.
    # We only ensure a NullHandler is present so the library stays silent by
    # default; attaching real handlers/levels is the application's job via
    # ``setup_kaos_logging``.
    _install_null_handler()
    return logging.getLogger(name)
