"""Helpers for parsing OAuth 2.0 token endpoint responses.

Used by both flow runners and the refresh helper. Centralized here
so the parser stays tested and the flow runners stay terse.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import SecretStr

from kaos_core.auth.errors import OAuthFlowError
from kaos_core.config.auth import OAuthToken


def parse_token_response(
    payload: dict[str, Any],
    *,
    issuer: str,
    client_id: str,
    fallback_refresh_token: str | None = None,
) -> OAuthToken:
    """Build an :class:`OAuthToken` from a token endpoint JSON payload.

    Per RFC 6749 §5.1, ``access_token`` and ``token_type`` are
    required; ``expires_in``, ``refresh_token``, and ``scope`` are
    optional. We compute ``expires_at`` (absolute ISO timestamp) as
    ``now + expires_in`` so consumers don't need to remember when
    the response landed.

    OAuth 2.1 SHOULD rotate the refresh token; if the response
    omits ``refresh_token`` (some providers do this on refresh —
    they reuse the existing one), we fall back to
    *fallback_refresh_token* so the new :class:`OAuthToken` still
    has a usable refresh token.
    """
    if "error" in payload:
        msg = (
            f"OAuth error from {issuer}: {payload['error']}"
            f"{': ' + payload['error_description'] if 'error_description' in payload else ''}"
        )
        raise OAuthFlowError(msg)

    access_token = payload.get("access_token")
    token_type = payload.get("token_type")
    if not access_token or not token_type:
        msg = (
            f"OAuth response from {issuer} is missing required fields 'access_token' / 'token_type'"
        )
        raise OAuthFlowError(msg)

    expires_in = payload.get("expires_in")
    expires_at: str | None = None
    if isinstance(expires_in, int):
        expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()

    refresh_token_raw = payload.get("refresh_token") or fallback_refresh_token
    scope = payload.get("scope")

    return OAuthToken(
        access_token=SecretStr(access_token),
        token_type=token_type,
        expires_at=expires_at,
        refresh_token=SecretStr(refresh_token_raw) if refresh_token_raw else None,
        scope=scope,
        issuer=issuer,
        client_id=client_id,
        obtained_at=datetime.now(UTC).isoformat(),
    )


__all__ = ["parse_token_response"]
