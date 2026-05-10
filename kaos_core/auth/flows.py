"""AuthFlow Protocol + FlowSelector heuristic.

:class:`AuthFlow` is the surface every concrete flow runner
implements: a single ``run()`` coroutine that takes the IdP-side
OAuth metadata (client_id, scopes, endpoints) and returns a fresh
:class:`OAuthToken`.

:class:`FlowSelector` picks between the loopback and device-code
flows at runtime. The default heuristic is conservative — prefer
loopback when a graphical session is available, otherwise device.
Callers can force either path explicitly; CLI ``--device-flow`` or
``--browser`` flags should map to ``force_device`` /
``force_loopback`` rather than the heuristic.
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from kaos_core.config.auth import OAuthToken


@runtime_checkable
class AuthFlow(Protocol):
    """A provider-agnostic OAuth 2.0 / 2.1 flow runner.

    Concrete implementations: :class:`PKCELoopbackFlow`,
    :class:`DeviceCodeFlow`. Both produce an :class:`OAuthToken`
    populated with ``issuer`` and ``client_id`` so the token can be
    refreshed without re-running the flow.
    """

    async def run(
        self,
        *,
        client_id: str,
        scopes: Sequence[str],
        authorization_endpoint: str,
        token_endpoint: str,
        device_authorization_endpoint: str | None = None,
    ) -> OAuthToken: ...


@dataclass
class FlowSelector:
    """Pick a flow runner based on the runtime environment.

    The default heuristic chooses loopback when:

    1. A graphical session is available
       (``DISPLAY`` / ``WAYLAND_DISPLAY`` set, or platform is
       macOS / Windows where the desktop is implicit).
    2. We can bind ``127.0.0.1`` on a port at all.

    Otherwise the selector returns the device-code flow. Callers
    pin the choice with ``force_loopback=True`` or
    ``force_device=True``.

    Args:
        force_loopback: Always return :class:`PKCELoopbackFlow`.
        force_device: Always return :class:`DeviceCodeFlow`.
        loopback_port_range: ``(low, high)`` inclusive port range
            for the loopback callback. Default is the IANA dynamic
            range ``[49152, 65535]``.
    """

    force_loopback: bool = False
    force_device: bool = False
    loopback_port_range: tuple[int, int] = field(default=(49152, 65535))

    def __post_init__(self) -> None:
        if self.force_loopback and self.force_device:
            msg = "force_loopback and force_device are mutually exclusive"
            raise ValueError(msg)
        low, high = self.loopback_port_range
        if not (1024 <= low <= high <= 65535):
            msg = f"loopback_port_range out of bounds: {self.loopback_port_range}"
            raise ValueError(msg)

    def pick(self) -> AuthFlow:
        # Local import to avoid circular dependency at module load.
        from kaos_core.auth.device_flow import DeviceCodeFlow
        from kaos_core.auth.pkce_loopback import PKCELoopbackFlow

        if self.force_loopback:
            return PKCELoopbackFlow(port_range=self.loopback_port_range)
        if self.force_device:
            return DeviceCodeFlow()
        if self._loopback_is_viable():
            return PKCELoopbackFlow(port_range=self.loopback_port_range)
        return DeviceCodeFlow()

    def _loopback_is_viable(self) -> bool:
        if not _has_graphical_session():
            return False
        return _can_bind_loopback()


def _has_graphical_session() -> bool:
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _can_bind_loopback() -> bool:
    """Probe whether we can bind any port on 127.0.0.1.

    Best-effort: tries port 0 (kernel-chosen). If the kernel refuses
    the bind (very rare; typically a sandbox without network namespace
    access) we treat loopback as unavailable. The actual flow runner
    will pick a port from the configured range when it runs.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return True
    except OSError:
        return False


__all__ = ["AuthFlow", "FlowSelector"]
