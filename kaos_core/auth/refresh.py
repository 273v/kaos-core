"""OAuth 2.0 refresh-token grant.

Single async helper that POSTs ``grant_type=refresh_token`` to the
token endpoint recorded in an :class:`OAuthToken` and returns a
fresh :class:`OAuthToken`. The caller is responsible for persisting
the returned token: per OAuth 2.1, the previous refresh token is
invalidated server-side after rotation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kaos_core.auth._token_response import parse_token_response
from kaos_core.auth.errors import OAuthFlowError

if TYPE_CHECKING:
    import httpx

    from kaos_core.config.auth import OAuthToken


async def refresh_token(
    token: OAuthToken,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 30.0,
) -> OAuthToken:
    """Exchange the token's refresh_token for a new :class:`OAuthToken`.

    The returned token has a fresh ``access_token``, ``expires_at``,
    and (per OAuth 2.1 rotation) usually a fresh ``refresh_token``.
    When the IdP omits a new refresh token in the response, the
    existing one is reused — some providers signal "rotation
    disabled" this way.

    Args:
        token: A token obtained from a flow runner. Must have
            ``issuer``, ``client_id``, and ``refresh_token`` set.
        client: Optional pre-configured :class:`httpx.AsyncClient`.
            When ``None``, a short-lived client is constructed and
            closed.
        timeout: Per-request timeout in seconds. Default 30s; tune
            down for interactive CLIs, up for slow IdPs.

    Raises:
        OAuthFlowError: The token doesn't carry the metadata needed
            for refresh, or the IdP returned an OAuth error
            response, or the response was malformed.
        httpx.HTTPError: Transport-level failure (DNS, TLS, timeout,
            etc.) — propagated as-is so callers can distinguish
            retryable from terminal errors.
    """
    import httpx  # local import keeps base install httpx-free

    if token.refresh_token is None:
        msg = "Token has no refresh_token; cannot refresh"
        raise OAuthFlowError(msg)
    if not token.issuer:
        msg = "Token has no issuer (token endpoint URL); cannot refresh"
        raise OAuthFlowError(msg)
    if not token.client_id:
        msg = "Token has no client_id; cannot refresh"
        raise OAuthFlowError(msg)

    refresh_value = token.refresh_token.get_secret_value()
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_value,
        "client_id": token.client_id,
    }

    async def _post(c: httpx.AsyncClient) -> httpx.Response:
        return await c.post(token.issuer or "", data=form, timeout=timeout)

    if client is None:
        async with httpx.AsyncClient() as managed_client:
            response = await _post(managed_client)
    else:
        response = await _post(client)

    try:
        payload = response.json()
    except ValueError as exc:
        msg = (
            f"OAuth refresh response from {token.issuer} is not JSON "
            f"(status {response.status_code})"
        )
        raise OAuthFlowError(msg) from exc

    return parse_token_response(
        payload,
        issuer=token.issuer,
        client_id=token.client_id,
        fallback_refresh_token=refresh_value,
    )


__all__ = ["refresh_token"]
