"""Exceptions raised by the OAuth flow runners and refresh helpers."""

from __future__ import annotations


class OAuthError(Exception):
    """Base class for all kaos_core.auth errors."""


class OAuthFlowError(OAuthError):
    """A flow runner failed mid-execution.

    Wraps protocol-level failures (the IdP returned an OAuth 2 error
    response, the callback didn't arrive, the state didn't match) so
    callers can distinguish them from transport-level
    :class:`httpx.HTTPError`.
    """


__all__ = ["OAuthError", "OAuthFlowError"]
