"""Regression test for audit-04 F-002: capability layer top-level re-export.

audit-04/kaos-core.md F-002 flagged that `kaos_core.types.capability`
exports `Capability`, `CapabilityKind`, `CostClass`, `LatencyClass`,
and `EMPTY_CAPABILITIES`, but the top-level facade (`kaos_core`) did
not re-export them — forcing every downstream package (kaos-agents
in particular) to dig into the typed submodule path. Other capability
classes (`ToolCapability`, `ResourcesCapability`, `RootsCapability`)
WERE already re-exported, so the gap was inconsistent and surprising.

This test pins the intended top-level surface so a future refactor
can't quietly drop the re-export and re-open F-002.
"""

from __future__ import annotations

import kaos_core


def test_capability_layer_is_reexported_at_top_level() -> None:
    """Pin the capability re-export contract.

    Pull from the typed submodule and from the top-level facade; assert
    they're identity-equal (same class objects, not lookalikes). This
    catches the obvious regression (someone re-defines a fresh class at
    the top level) as well as the silent regression (the import is
    removed and a `__getattr__` shim returns something else).
    """
    from kaos_core.types.capability import (
        EMPTY_CAPABILITIES,
        Capability,
        CapabilityKind,
        CostClass,
        LatencyClass,
    )

    assert kaos_core.Capability is Capability
    assert kaos_core.CapabilityKind is CapabilityKind
    assert kaos_core.CostClass is CostClass
    assert kaos_core.LatencyClass is LatencyClass
    assert kaos_core.EMPTY_CAPABILITIES is EMPTY_CAPABILITIES


def test_capability_names_appear_in_dunder_all() -> None:
    """`__all__` is the wildcard-import contract; new names belong here.

    Without this assertion, `from kaos_core import *` would skip the
    capability layer even when the module-level imports succeed.
    """
    for name in (
        "Capability",
        "CapabilityKind",
        "CostClass",
        "LatencyClass",
        "EMPTY_CAPABILITIES",
    ):
        assert name in kaos_core.__all__, (
            f"audit-04 F-002 regression: {name!r} missing from kaos_core.__all__"
        )
