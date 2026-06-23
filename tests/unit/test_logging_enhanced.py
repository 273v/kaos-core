"""Tests for enhanced get_logger() with auto-prefix."""

from __future__ import annotations

import logging

from kaos_core.base.context import KaosContext
from kaos_core.logging import get_logger, setup_kaos_logging


class TestGetLoggerAutoPrefix:
    def test_kaos_underscore_prefix(self) -> None:
        """kaos_web.clients.http → kaos.web.clients.http."""
        logger = get_logger("kaos_web.clients.http")
        assert logger.name == "kaos.web.clients.http"

    def test_kaos_dot_prefix_unchanged(self) -> None:
        """kaos.context stays as-is."""
        logger = get_logger("kaos.context")
        assert logger.name == "kaos.context"

    def test_bare_module_gets_prefix(self) -> None:
        """my_module → kaos.my_module."""
        logger = get_logger("my_module")
        assert logger.name == "kaos.my_module"

    def test_kaos_exact_unchanged(self) -> None:
        """'kaos' root stays as-is."""
        logger = get_logger("kaos")
        assert logger.name == "kaos"

    def test_kaos_underscore_single_module(self) -> None:
        """kaos_pdf → kaos.pdf."""
        logger = get_logger("kaos_pdf")
        assert logger.name == "kaos.pdf"

    def test_kaos_underscore_nested(self) -> None:
        """kaos_office.docx.reader → kaos.office.docx.reader."""
        logger = get_logger("kaos_office.docx.reader")
        assert logger.name == "kaos.office.docx.reader"


class TestLoggerHierarchy:
    def test_child_inherits_kaos_root(self) -> None:
        """Loggers under kaos.* should inherit from the kaos root."""
        setup_kaos_logging(force=True)
        root = logging.getLogger("kaos")
        child = get_logger("kaos_web.extract")
        # Child is under kaos hierarchy
        assert child.name == "kaos.web.extract"
        assert child.parent is not None
        # Walk up to find kaos root
        parent = child.parent
        while parent and parent.name != "kaos":
            parent = parent.parent
        assert parent is root


class TestLibrarySilentByDefault:
    """The library must not auto-configure logging (no real handlers, no level
    set) as a side effect of import or normal operation. Only an application
    calling ``setup_kaos_logging`` may attach a real handler."""

    def _reset_kaos_logger(self) -> None:
        root = logging.getLogger("kaos")
        root.handlers.clear()
        root.setLevel(logging.NOTSET)
        root.propagate = True

    def test_get_logger_does_not_attach_real_handler(self) -> None:
        self._reset_kaos_logger()
        get_logger("kaos_office.docx.writer")
        root = logging.getLogger("kaos")
        # Only a NullHandler may be present; never a StreamHandler/FileHandler.
        real = [h for h in root.handlers if not isinstance(h, logging.NullHandler)]
        assert real == []
        # The library must not have set a level.
        assert root.level == logging.NOTSET

    def test_get_logger_installs_null_handler(self) -> None:
        self._reset_kaos_logger()
        get_logger("kaos.something")
        root = logging.getLogger("kaos")
        assert any(isinstance(h, logging.NullHandler) for h in root.handlers)

    def test_emit_is_silent_without_setup(self, capsys) -> None:  # type: ignore[no-untyped-def]
        self._reset_kaos_logger()
        logger = get_logger("kaos_office.docx.writer")
        logger.info("docx.writer: wrote untitled, blocks=2")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_app_can_configure_after_default(self) -> None:
        self._reset_kaos_logger()
        get_logger("kaos.something")  # installs NullHandler
        logger = setup_kaos_logging(log_level="DEBUG", force=True)
        real = [h for h in logger.handlers if not isinstance(h, logging.NullHandler)]
        assert len(real) == 1
        assert logger.level == logging.DEBUG


def test_context_logging_uses_current_context_ids() -> None:
    records: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("kaos.context")
    old_handlers = list(logger.handlers)
    old_filters = list(logger.filters)
    old_level = logger.level
    old_propagate = logger.propagate
    handler = CaptureHandler()
    logger.handlers = [handler]
    logger.filters.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        first = KaosContext(session_id="session-a", trace_id="trace-a")
        second = KaosContext(session_id="session-b", trace_id="trace-b")

        first.info("from first")
        second.info("from second")
    finally:
        logger.handlers = old_handlers
        logger.filters.clear()
        logger.filters.extend(old_filters)
        logger.setLevel(old_level)
        logger.propagate = old_propagate

    assert [
        (r.__dict__["session_id"], r.__dict__["trace_id"], r.getMessage()) for r in records
    ] == [
        ("session-a", "trace-a", "from first"),
        ("session-b", "trace-b", "from second"),
    ]
