"""Tests for ``AuthFlow`` Protocol + ``FlowSelector``.

Selector heuristics are tested by manipulating ``DISPLAY``,
``WAYLAND_DISPLAY``, and the loopback bind probe. Forced-flow paths
are tested by constructing the selector with ``force_loopback`` /
``force_device``.
"""

from __future__ import annotations

import sys

import pytest

from kaos_core.auth import (
    AuthFlow,
    DeviceCodeFlow,
    FlowSelector,
    PKCELoopbackFlow,
)


def test_flow_selector_default_construction() -> None:
    selector = FlowSelector()
    assert selector.force_loopback is False
    assert selector.force_device is False


def test_force_loopback_returns_pkce_runner() -> None:
    selector = FlowSelector(force_loopback=True)
    flow = selector.pick()
    assert isinstance(flow, PKCELoopbackFlow)


def test_force_device_returns_device_runner() -> None:
    selector = FlowSelector(force_device=True)
    flow = selector.pick()
    assert isinstance(flow, DeviceCodeFlow)


def test_force_both_raises() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        FlowSelector(force_loopback=True, force_device=True)


def test_invalid_port_range_raises() -> None:
    with pytest.raises(ValueError, match="out of bounds"):
        FlowSelector(loopback_port_range=(100, 200))  # < 1024
    with pytest.raises(ValueError, match="out of bounds"):
        FlowSelector(loopback_port_range=(60000, 50000))  # low > high


def test_default_picks_loopback_with_display(monkeypatch: pytest.MonkeyPatch) -> None:
    if sys.platform != "linux":
        pytest.skip("DISPLAY heuristic is Linux-specific")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    selector = FlowSelector()
    flow = selector.pick()
    assert isinstance(flow, PKCELoopbackFlow)


def test_default_picks_device_when_headless(monkeypatch: pytest.MonkeyPatch) -> None:
    if sys.platform != "linux":
        pytest.skip("headless heuristic is Linux-specific")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    selector = FlowSelector()
    flow = selector.pick()
    assert isinstance(flow, DeviceCodeFlow)


def test_default_picks_loopback_on_macos_or_windows() -> None:
    if sys.platform not in ("darwin", "win32"):
        pytest.skip("graphical-implicit on macOS/Windows only")
    selector = FlowSelector()
    flow = selector.pick()
    assert isinstance(flow, PKCELoopbackFlow)


def test_pkce_loopback_implements_authflow_protocol() -> None:
    flow: AuthFlow = PKCELoopbackFlow()
    assert hasattr(flow, "run")


def test_device_code_implements_authflow_protocol() -> None:
    flow: AuthFlow = DeviceCodeFlow()
    assert hasattr(flow, "run")
