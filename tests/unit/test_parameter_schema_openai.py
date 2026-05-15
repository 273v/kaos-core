"""OpenAI-compatibility unit tests for ``ParameterSchema.to_json_schema``.

OpenAI's function-calling API uses a stricter subset of JSON Schema than
Anthropic. The two rules that have already bitten bridged KAOS tools:

1. ``type=array`` must declare ``items``. Anthropic accepts loose arrays;
   OpenAI rejects them with HTTP 400 ``invalid_function_parameters``.
2. The whole payload must validate as Draft 2020-12 JSON Schema. Common
   misses include putting ``minimum`` on a non-numeric field or using
   ``enum`` with non-string values.

These tests pin both:
- A repo-local check that ``to_json_schema`` emits ``items`` for every
  array (the defensive floor we shipped, plus any caller override).
- An optional Draft 2020-12 validation step that runs when the
  ``jsonschema`` library is importable. The fast gate stays light by
  skipping when the dep is absent; CI runs with ``jsonschema`` installed.
"""

from __future__ import annotations

import pytest

from kaos_core.types import ParameterSchema


def test_array_without_items_gets_defensive_default() -> None:
    """The floor: ``type=array`` with no constraints emits ``items: {}``.

    Without this, OpenAI's strict validator rejected the entire tool
    catalog when even one bridged tool (kaos-pdf-extract-parse,
    kaos-office-parse-xlsx, etc.) forgot to declare item types.
    See FIX-14 in the project tracker for the live incident.
    """
    schema = ParameterSchema(
        name="pages",
        type="array",
        description="0-based page indices.",
        required=False,
    ).to_json_schema()
    assert schema["type"] == "array"
    assert "items" in schema, "array without items breaks OpenAI tool-call"
    # Default is "accept anything" — callers should override for real
    # element types but the floor must always be present.
    assert schema["items"] == {}


def test_array_with_caller_items_preserved() -> None:
    """Explicit ``items`` in constraints overrides the defensive floor."""
    schema = ParameterSchema(
        name="page_indices",
        type="array",
        constraints={"items": {"type": "integer", "minimum": 0}, "minItems": 1},
    ).to_json_schema()
    assert schema["items"] == {"type": "integer", "minimum": 0}
    assert schema["minItems"] == 1


def test_non_array_does_not_inject_items() -> None:
    """Defensive floor must not contaminate non-array schemas."""
    for type_name in ("string", "integer", "number", "boolean", "object"):
        schema = ParameterSchema(name=f"p_{type_name}", type=type_name).to_json_schema()
        assert "items" not in schema, f"{type_name} schema unexpectedly carries items"


def test_object_array_items_schema_round_trips() -> None:
    """Complex item shapes (objects with required fields) survive serialization.

    This is the kaos-tabular aggregates / order_by pattern: array of
    typed-object items. The serializer must preserve the nested
    ``properties`` and ``required`` arrays so OpenAI gets the full
    contract.
    """
    schema = ParameterSchema(
        name="aggregates",
        type="array",
        constraints={
            "items": {
                "type": "object",
                "properties": {
                    "func": {"type": "string", "enum": ["sum", "avg", "count"]},
                    "column": {"type": "string"},
                    "alias": {"type": "string"},
                },
                "required": ["func", "column"],
            },
            "minItems": 1,
        },
    ).to_json_schema()
    items = schema["items"]
    assert items["type"] == "object"
    assert items["required"] == ["func", "column"]
    assert items["properties"]["func"]["enum"] == ["sum", "avg", "count"]
    assert schema["minItems"] == 1


def test_required_and_default_round_trip() -> None:
    """Optional params propagate ``default`` only when value is set."""
    optional_with_default = ParameterSchema(
        name="limit",
        type="integer",
        required=False,
        default=100,
        constraints={"minimum": 1, "maximum": 500},
    ).to_json_schema()
    assert optional_with_default["default"] == 100
    assert optional_with_default["minimum"] == 1

    optional_no_default = ParameterSchema(
        name="optional",
        type="string",
        required=False,
    ).to_json_schema()
    assert "default" not in optional_no_default


def test_draft_2020_12_validates() -> None:
    """End-to-end: every shape we emit is valid Draft 2020-12 JSON Schema.

    Skipped when ``jsonschema`` isn't installed so the fast unit-test gate
    stays dep-free. CI should install ``jsonschema`` so this runs.
    """
    jsonschema = pytest.importorskip("jsonschema")
    validator_cls = jsonschema.Draft202012Validator

    cases = [
        ParameterSchema(name="text", type="string"),
        ParameterSchema(name="page", type="integer", constraints={"minimum": 0}),
        ParameterSchema(name="ratio", type="number"),
        ParameterSchema(name="flag", type="boolean"),
        ParameterSchema(name="any_array", type="array"),  # defensive floor
        ParameterSchema(
            name="typed_array",
            type="array",
            constraints={"items": {"type": "string"}, "minItems": 1},
        ),
        ParameterSchema(
            name="objects",
            type="array",
            constraints={
                "items": {
                    "type": "object",
                    "properties": {"k": {"type": "string"}},
                    "required": ["k"],
                }
            },
        ),
    ]
    for param in cases:
        schema = param.to_json_schema()
        validator_cls.check_schema(schema)  # raises on invalid
