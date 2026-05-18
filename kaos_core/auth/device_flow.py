"""RFC 8628 — OAuth 2.0 Device Authorization Grant.

The headless / SSH / WSL alternative to PKCE+loopback: the IdP
issues a short user-readable code and a verification URL; the
user signs in on a separate device (phone, another laptop) while
the CLI polls the token endpoint until the user authorizes.

Flow:

1. POST to ``device_authorization_endpoint`` with ``client_id``
   and ``scope``. Receive ``device_code``, ``user_code``,
   ``verification_uri`` (and possibly
   ``verification_uri_complete``), ``interval``, ``expires_in``.
2. Display the user_code + verification_uri to the user via
   stdout (or a caller-supplied display callback).
3. Poll ``token_endpoint`` with
   ``grant_type=urn:ietf:params:oauth:grant-type:device_code``.
   The IdP responds with one of:
   - ``authorization_pending``: keep polling at the configured
     interval.
   - ``slow_down``: increase the polling interval by 5 seconds.
   - ``access_denied`` / ``expired_token``: bail.
   - A token payload: success.

Injection points (all keyword-only):

- ``http_client`` — pre-configured :class:`httpx.AsyncClient`.
- ``display`` — callable that receives the
  :class:`DeviceAuthorization` response so the caller can present
  the user_code + URI in their preferred UI (CLI, GUI, log).
- ``poll_sleep`` — coroutine factory invoked between polls. The
  default uses :func:`asyncio.sleep`. Tests inject a no-op to
  fast-forward through the polling loop.
- ``security_settings`` — optional outbound URL and response-size
  policy. OAuth endpoints default to HTTPS-only plus the standard
  private-network, loopback, metadata-service, and size guards.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kaos_core.auth._http_safety import response_json, validate_oauth_endpoint
from kaos_core.auth._token_response import parse_token_response
from kaos_core.auth.errors import OAuthFlowError
from kaos_core.logging import get_logger

if TYPE_CHECKING:
    import httpx

    from kaos_core.config.auth import OAuthToken
    from kaos_core.security.settings import KaosSecuritySettings

logger = get_logger(__name__)


@dataclass(frozen=True)
class DeviceAuthorization:
    """Decoded RFC 8628 §3.2 device-authorization response.

    Carries everything the user needs to authorize on a separate
    device. Instances are passed to a *display* callback so callers
    can present the data in their preferred UI.
    """

    device_code: str
    user_code: str
    verification_uri: str
    interval: int = 5
    expires_in: int = 1800
    verification_uri_complete: str | None = None


def _default_display(auth: DeviceAuthorization) -> None:
    """Print the device-flow instructions to stdout."""
    target = auth.verification_uri_complete or auth.verification_uri
    print()
    print("Open this URL on a phone or another browser:")
    print(f"  {target}")
    if not auth.verification_uri_complete:
        print(f"\nAnd enter the code: {auth.user_code}")
    print()


PollSleepCallable = Callable[[float], Awaitable[None]]


async def _default_poll_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


@dataclass
class DeviceCodeFlow:
    """RFC 8628 device authorization flow runner.

    Args:
        timeout_seconds: Hard upper bound on total wall time
            spent polling. Defaults to 30 minutes — most IdPs
            expire the device_code at 15-30 minutes anyway.
        slow_down_increment: Seconds to add to the polling interval
            on each ``slow_down`` response. RFC 8628 §3.5 specifies
            "5 seconds is RECOMMENDED".
        http_client: Pre-configured :class:`httpx.AsyncClient`.
        display: Callable receiving the :class:`DeviceAuthorization`
            for user-facing presentation.
        poll_sleep: Coroutine factory for the delay between polls.
            Tests inject a no-op.
        security_settings: Optional outbound URL and response-size
            policy. OAuth endpoints default to HTTPS-only plus the
            standard private-network, loopback, metadata-service, and
            size guards.
        allowed_endpoint_schemes: Schemes accepted for OAuth endpoints.
            Defaults to HTTPS-only; local test IdPs can opt into HTTP
            explicitly.
    """

    timeout_seconds: float = 1800.0
    slow_down_increment: int = 5
    http_client: httpx.AsyncClient | None = None
    display: Callable[[DeviceAuthorization], None] = _default_display
    poll_sleep: PollSleepCallable = _default_poll_sleep
    security_settings: KaosSecuritySettings | None = None
    allowed_endpoint_schemes: tuple[str, ...] = ("https",)

    async def run(
        self,
        *,
        client_id: str,
        scopes: Sequence[str],
        authorization_endpoint: str,
        token_endpoint: str,
        device_authorization_endpoint: str | None = None,
    ) -> OAuthToken:
        del authorization_endpoint  # not used; kept for AuthFlow Protocol
        if not device_authorization_endpoint:
            msg = "DeviceCodeFlow requires device_authorization_endpoint"
            raise OAuthFlowError(msg)

        import httpx

        async def _run_with_client(client: httpx.AsyncClient) -> OAuthToken:
            auth = await self._authorize(
                client,
                client_id=client_id,
                scopes=scopes,
                device_authorization_endpoint=device_authorization_endpoint,
            )
            self.display(auth)
            return await self._poll_for_token(
                client,
                client_id=client_id,
                token_endpoint=token_endpoint,
                auth=auth,
            )

        if self.http_client is None:
            async with httpx.AsyncClient() as managed_client:
                return await _run_with_client(managed_client)
        return await _run_with_client(self.http_client)

    async def _authorize(
        self,
        client: httpx.AsyncClient,
        *,
        client_id: str,
        scopes: Sequence[str],
        device_authorization_endpoint: str,
    ) -> DeviceAuthorization:
        form = {"client_id": client_id, "scope": " ".join(scopes)}
        endpoint = validate_oauth_endpoint(
            device_authorization_endpoint,
            label="Device authorization endpoint",
            settings=self.security_settings,
            allowed_schemes=self.allowed_endpoint_schemes,
        )
        response = await client.post(endpoint, data=form, timeout=self.timeout_seconds)
        payload = response_json(
            response,
            label="Device authorization endpoint",
            settings=self.security_settings,
        )

        if "error" in payload:
            msg = f"Device authorization error: {payload.get('error')}"
            raise OAuthFlowError(msg)
        device_code = payload.get("device_code")
        user_code = payload.get("user_code")
        verification_uri = payload.get("verification_uri")
        if not device_code or not user_code or not verification_uri:
            msg = (
                "Device authorization response is missing required fields "
                "device_code/user_code/verification_uri"
            )
            raise OAuthFlowError(msg)
        return DeviceAuthorization(
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            interval=int(payload.get("interval", 5)),
            expires_in=int(payload.get("expires_in", 1800)),
            verification_uri_complete=payload.get("verification_uri_complete"),
        )

    async def _poll_for_token(
        self,
        client: httpx.AsyncClient,
        *,
        client_id: str,
        token_endpoint: str,
        auth: DeviceAuthorization,
    ) -> OAuthToken:
        interval = float(auth.interval)
        deadline = min(self.timeout_seconds, float(auth.expires_in))
        elapsed = 0.0
        form = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": auth.device_code,
            "client_id": client_id,
        }

        while elapsed < deadline:
            await self.poll_sleep(interval)
            elapsed += interval
            endpoint = validate_oauth_endpoint(
                token_endpoint,
                label="Token endpoint",
                settings=self.security_settings,
                allowed_schemes=self.allowed_endpoint_schemes,
            )
            response = await client.post(endpoint, data=form, timeout=self.timeout_seconds)
            payload = response_json(
                response,
                label="Token endpoint",
                settings=self.security_settings,
            )

            error = payload.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += self.slow_down_increment
                continue
            if error in ("access_denied", "expired_token"):
                msg = f"Device authorization failed: {error}"
                raise OAuthFlowError(msg)
            if error:
                # Any other error — surface it.
                return parse_token_response(payload, issuer=endpoint, client_id=client_id)
            # No error means a successful token response.
            return parse_token_response(payload, issuer=endpoint, client_id=client_id)

        msg = f"Device authorization timed out after {elapsed:.0f}s"
        raise OAuthFlowError(msg)


__all__ = ["DeviceAuthorization", "DeviceCodeFlow"]
