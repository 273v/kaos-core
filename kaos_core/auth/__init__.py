"""OAuth flow runners and refresh helpers (F2.4).

Provider-agnostic OAuth 2.0 / 2.1 plumbing that produces
:class:`kaos_core.config.OAuthToken` objects. Two flows ship today:

- :class:`PKCELoopbackFlow` (RFC 7636 + RFC 8252 §7.3) for desktop
  CLIs with a usable browser. Binds an ephemeral 127.0.0.1 port,
  opens the browser, waits for the OAuth callback.
- :class:`DeviceCodeFlow` (RFC 8628) for headless / SSH / WSL where
  binding a loopback callback isn't reliable. Polls the token
  endpoint with the device code until the user authorizes on a
  separate device.

:class:`FlowSelector` picks between the two based on a simple
heuristic (browser available + can bind loopback → loopback;
otherwise device flow). Callers can force either with
``force_loopback`` or ``force_device``.

Refresh: :func:`refresh_token` does the
``grant_type=refresh_token`` POST against the token's recorded
issuer. OAuth 2.1 mandates refresh-token rotation for public
clients, so the function returns a *new* :class:`OAuthToken` —
callers must persist the returned token (the old refresh token is
already invalid server-side).

Optional dependency footprint: this subpackage requires
``kaos-core[oauth]`` (``httpx>=0.28``). The base install does not
import this subpackage; importing :mod:`kaos_core.auth` raises
:class:`ImportError` with an actionable message when ``httpx`` is
missing.
"""

from __future__ import annotations

# Probe httpx at import so a misconfigured environment fails loudly
# at the right place instead of deep inside a flow runner.
try:
    import httpx as _httpx  # noqa: F401
except ImportError as exc:  # pragma: no cover - covered by env probe
    msg = (
        "kaos_core.auth requires httpx. Install kaos-core[oauth] to enable the OAuth flow runners."
    )
    raise ImportError(msg) from exc

from kaos_core.auth.device_flow import DeviceCodeFlow
from kaos_core.auth.errors import OAuthError, OAuthFlowError
from kaos_core.auth.flows import AuthFlow, FlowSelector
from kaos_core.auth.pkce_loopback import PKCELoopbackFlow
from kaos_core.auth.refresh import refresh_token

__all__ = [
    "AuthFlow",
    "DeviceCodeFlow",
    "FlowSelector",
    "OAuthError",
    "OAuthFlowError",
    "PKCELoopbackFlow",
    "refresh_token",
]
