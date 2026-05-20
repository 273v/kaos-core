"""Unit tests for :mod:`kaos_core.types.capability`.

Capability is a frozen value type that subsumes the planner's mental
model of "tool" / "source" / "retriever" / "judge" / "persona" / "UI
surface". See ``kaos-modules/docs/plans/2026-05-19-lateral-redesign-
capability-layer.md`` for context.
"""

from __future__ import annotations

import dataclasses

import pytest

from kaos_core.types import (
    EMPTY_CAPABILITIES,
    Capability,
    CapabilityKind,
    CostClass,
    LatencyClass,
)


class TestCapability:
    def test_minimal_construction(self) -> None:
        c = Capability(
            name="retrieve",
            kind=CapabilityKind.SEARCH,
            description="Find pointers to information across configured sources.",
        )
        assert c.name == "retrieve"
        assert c.kind == CapabilityKind.SEARCH
        assert c.cost_class == CostClass.MODERATE
        assert c.latency_class == LatencyClass.MODERATE
        assert c.side_effects is False
        assert c.inputs == ()
        assert c.outputs == ()
        assert c.preconditions == ()
        assert c.tags == ()
        assert c.backing_tool_names == ()

    def test_full_construction(self) -> None:
        c = Capability(
            name="discover",
            kind=CapabilityKind.SEARCH,
            description="Follow links from a seed URL to build a corpus.",
            inputs=("seed_url", "max_depth", "link_filter"),
            outputs=("ContentDocument[]",),
            cost_class=CostClass.EXPENSIVE,
            latency_class=LatencyClass.SLOW,
            side_effects=False,
            preconditions=("session.has_browser",),
            tags=("crawl", "discovery"),
            backing_tool_names=("kaos-web-crawl-bfs", "kaos-web-discover"),
        )
        assert c.cost_class == CostClass.EXPENSIVE
        assert c.latency_class == LatencyClass.SLOW
        assert "kaos-web-crawl-bfs" in c.backing_tool_names

    def test_frozen(self) -> None:
        c = Capability(
            name="x",
            kind=CapabilityKind.READ,
            description="x",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            # Use ``setattr`` so the test exercises the dataclass-
            # installed ``__setattr__`` (which is what raises). The
            # type checker would also flag the direct ``c.name = ...``
            # form as an error against the read-only property; ``setattr``
            # is a runtime check.
            setattr(c, "name", "y")  # noqa: B010

    def test_slotted(self) -> None:
        c = Capability(
            name="x",
            kind=CapabilityKind.READ,
            description="x",
        )
        # __slots__ disables instance __dict__ — confirms slots=True
        with pytest.raises(AttributeError):
            c.__dict__  # noqa: B018

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            Capability(
                name="",
                kind=CapabilityKind.READ,
                description="x",
            )
        with pytest.raises(ValueError, match="non-empty"):
            Capability(
                name="   ",
                kind=CapabilityKind.READ,
                description="x",
            )

    def test_empty_description_rejected(self) -> None:
        with pytest.raises(ValueError, match="description"):
            Capability(
                name="x",
                kind=CapabilityKind.READ,
                description="",
            )

    def test_mutate_requires_side_effects(self) -> None:
        with pytest.raises(ValueError, match="MUTATE"):
            Capability(
                name="write-file",
                kind=CapabilityKind.MUTATE,
                description="Write a file to disk.",
                side_effects=False,
            )
        # The same shape with side_effects=True succeeds.
        c = Capability(
            name="write-file",
            kind=CapabilityKind.MUTATE,
            description="Write a file to disk.",
            side_effects=True,
        )
        assert c.side_effects is True

    def test_hashable(self) -> None:
        a = Capability(name="x", kind=CapabilityKind.READ, description="x")
        b = Capability(name="x", kind=CapabilityKind.READ, description="x")
        assert hash(a) == hash(b)
        assert a == b
        # In a set
        assert len({a, b}) == 1


class TestCapabilityKind:
    def test_enum_values_stable(self) -> None:
        # Public-API contract: these string values are persisted in
        # event traces, logs, and registries. Don't reorder or rename.
        assert CapabilityKind.SEARCH == "search"
        assert CapabilityKind.READ == "read"
        assert CapabilityKind.EXTRACT == "extract"
        assert CapabilityKind.COMPUTE == "compute"
        assert CapabilityKind.JUDGE == "judge"
        assert CapabilityKind.DRAFT == "draft"
        assert CapabilityKind.MUTATE == "mutate"
        assert CapabilityKind.GRAPH == "graph"
        assert CapabilityKind.META == "meta"

    def test_str_enum_round_trip(self) -> None:
        # CapabilityKind is StrEnum so it round-trips through plain string.
        assert CapabilityKind("search") == CapabilityKind.SEARCH
        with pytest.raises(ValueError):
            CapabilityKind("not-a-kind")


class TestCostAndLatencyClasses:
    def test_cost_class_values(self) -> None:
        assert CostClass.FREE == "free"
        assert CostClass.CHEAP == "cheap"
        assert CostClass.MODERATE == "moderate"
        assert CostClass.EXPENSIVE == "expensive"

    def test_latency_class_values(self) -> None:
        assert LatencyClass.INSTANT == "instant"
        assert LatencyClass.FAST == "fast"
        assert LatencyClass.MODERATE == "moderate"
        assert LatencyClass.SLOW == "slow"


class TestModuleExports:
    def test_empty_capabilities_is_immutable_tuple(self) -> None:
        assert EMPTY_CAPABILITIES == ()
        assert isinstance(EMPTY_CAPABILITIES, tuple)
