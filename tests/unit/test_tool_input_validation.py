"""Tests for KaosTool primitive-type input validation.

These tests cover the contract documented on
:meth:`kaos_core.base.tool.KaosTool.validate_inputs` — primitive JSON Schema
type checks. Full schema validation (enum, minimum/maximum, pattern, nested
properties, oneOf, $ref) is intentionally out of scope here; that work is
tracked for v0.2 via the ``jsonschema`` library.
"""

from __future__ import annotations

import pytest

from kaos_core.decorators import kaos_tool
from kaos_core.exceptions import ValidationError
from kaos_core.types.enums import ToolCapability, ToolCategory


@kaos_tool(
    name="kaos-test-validate-string",
    description="Echo a single string parameter",
    category=ToolCategory.DATA,
    capability=ToolCapability.TRANSFORM,
    auto_register=False,
)
async def echo_string(text: str) -> str:
    return text


@kaos_tool(
    name="kaos-test-validate-int",
    description="Multiply an integer by two",
    category=ToolCategory.DATA,
    capability=ToolCapability.TRANSFORM,
    auto_register=False,
)
async def double_int(n: int) -> int:
    return n * 2


@kaos_tool(
    name="kaos-test-validate-bool",
    description="Negate a boolean",
    category=ToolCategory.DATA,
    capability=ToolCapability.TRANSFORM,
    auto_register=False,
)
async def negate(flag: bool) -> bool:
    return not flag


@kaos_tool(
    name="kaos-test-validate-mixed",
    description="Three primitives plus an optional default",
    category=ToolCategory.DATA,
    capability=ToolCapability.TRANSFORM,
    auto_register=False,
)
async def mixed(n: int, name: str, ratio: float, verbose: bool = False) -> dict:
    return {"n": n, "name": name, "ratio": ratio, "verbose": verbose}


def test_required_field_missing_raises() -> None:
    with pytest.raises(ValidationError) as exc_info:
        echo_string.validate_inputs({})
    assert "text" in str(exc_info.value.details["fields"])


def test_well_typed_inputs_pass() -> None:
    assert echo_string.validate_inputs({"text": "hello"}) is True
    assert double_int.validate_inputs({"n": 7}) is True
    assert negate.validate_inputs({"flag": True}) is True


def test_string_param_rejects_int() -> None:
    with pytest.raises(ValidationError) as exc_info:
        echo_string.validate_inputs({"text": 123})
    assert any("text" in field for field in exc_info.value.details["fields"])
    assert any("string" in field for field in exc_info.value.details["fields"])


def test_integer_param_rejects_string() -> None:
    with pytest.raises(ValidationError) as exc_info:
        double_int.validate_inputs({"n": "not-int"})
    assert any("n" in field for field in exc_info.value.details["fields"])
    assert any("integer" in field for field in exc_info.value.details["fields"])


def test_integer_param_rejects_boolean() -> None:
    # bool is a subclass of int in Python but a distinct JSON type. Rejecting
    # it here matches what `jsonschema` validators do, so callers that pipe
    # validated inputs through to JSON-aware downstream consumers do not
    # silently coerce.
    with pytest.raises(ValidationError) as exc_info:
        double_int.validate_inputs({"n": True})
    assert any("boolean" in field for field in exc_info.value.details["fields"])


def test_boolean_param_rejects_int() -> None:
    with pytest.raises(ValidationError) as exc_info:
        negate.validate_inputs({"flag": 1})
    assert any("flag" in field for field in exc_info.value.details["fields"])
    assert any("boolean" in field for field in exc_info.value.details["fields"])


def test_number_param_accepts_int_and_float() -> None:
    # `number` in JSON Schema accepts both int and float.
    assert mixed.validate_inputs({"n": 1, "name": "x", "ratio": 1.5}) is True
    assert mixed.validate_inputs({"n": 1, "name": "x", "ratio": 2}) is True


def test_number_param_rejects_string_and_bool() -> None:
    with pytest.raises(ValidationError):
        mixed.validate_inputs({"n": 1, "name": "x", "ratio": "not-num"})
    with pytest.raises(ValidationError):
        mixed.validate_inputs({"n": 1, "name": "x", "ratio": True})


def test_optional_param_with_default_can_be_omitted() -> None:
    # `verbose` has a default so it is not required.
    assert mixed.validate_inputs({"n": 1, "name": "x", "ratio": 1.0}) is True


def test_multiple_type_errors_reported_together() -> None:
    with pytest.raises(ValidationError) as exc_info:
        mixed.validate_inputs({"n": "bad", "name": 123, "ratio": "also-bad", "verbose": "nope"})
    fields = exc_info.value.details["fields"]
    # All four should be flagged in the same exception.
    assert any("n:" in field for field in fields)
    assert any("name:" in field for field in fields)
    assert any("ratio:" in field for field in fields)
    assert any("verbose:" in field for field in fields)
