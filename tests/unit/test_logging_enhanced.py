"""Tests for enhanced get_logger() with auto-prefix."""

from __future__ import annotations

import logging

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
