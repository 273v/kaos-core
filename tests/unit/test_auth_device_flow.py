"""End-to-end test for ``DeviceCodeFlow``.

Mocks both the device authorization endpoint and the token endpoint
with :class:`httpx.MockTransport`. Polling delay is collapsed via
the ``poll_sleep`` injection point so the suite runs fast.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from kaos_core.auth import DeviceCodeFlow, OAuthFlowError
from kaos_core.auth.device_flow import DeviceAuthorization
from kaos_core.security import KaosSecuritySettings


def _silent_display(_: DeviceAuthorization) -> None:
    pass


async def _instant_sleep(_seconds: float) -> None:
    pass


def _make_handler(
    device_payload: dict | None = None,
    token_payloads: list[dict] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a routing handler over device + token endpoints.

    The token endpoint walks through ``token_payloads`` in order,
    one per poll. The device endpoint always returns
    ``device_payload`` (or a sensible default).
    """
    device = device_payload or {
        "device_code": "DEV-CODE",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://idp.example/device",
        "verification_uri_complete": "https://idp.example/device?code=ABCD-EFGH",
        "interval": 1,
        "expires_in": 60,
    }
    payloads = list(token_payloads or [{"access_token": "atk", "token_type": "Bearer"}])
    cursor = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "/device_authorization" in str(request.url):
            return httpx.Response(200, json=device)
        if "/token" in str(request.url):
            i = min(cursor["i"], len(payloads) - 1)
            cursor["i"] += 1
            return httpx.Response(200, json=payloads[i])
        return httpx.Response(404)

    return handler


@pytest.mark.asyncio
async def test_happy_path_first_poll_returns_token() -> None:
    handler = _make_handler(
        token_payloads=[
            {
                "access_token": "atk",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "rtk",
            },
        ]
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        flow = DeviceCodeFlow(
            http_client=client, display=_silent_display, poll_sleep=_instant_sleep
        )
        token = await flow.run(
            client_id="client-abc",
            scopes=["read"],
            authorization_endpoint="https://idp.example/authorize",
            token_endpoint="https://idp.example/token",
            device_authorization_endpoint="https://idp.example/device_authorization",
        )
    assert token.access_token.get_secret_value() == "atk"
    assert token.refresh_token is not None
    assert token.refresh_token.get_secret_value() == "rtk"
    assert token.issuer == "https://idp.example/token"
    assert token.client_id == "client-abc"


@pytest.mark.asyncio
async def test_authorization_pending_then_success() -> None:
    handler = _make_handler(
        token_payloads=[
            {"error": "authorization_pending"},
            {"error": "authorization_pending"},
            {"access_token": "atk", "token_type": "Bearer"},
        ]
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        flow = DeviceCodeFlow(
            http_client=client, display=_silent_display, poll_sleep=_instant_sleep
        )
        token = await flow.run(
            client_id="client-abc",
            scopes=["read"],
            authorization_endpoint="https://idp.example/authorize",
            token_endpoint="https://idp.example/token",
            device_authorization_endpoint="https://idp.example/device_authorization",
        )
    assert token.access_token.get_secret_value() == "atk"


@pytest.mark.asyncio
async def test_slow_down_increases_interval() -> None:
    handler = _make_handler(
        token_payloads=[
            {"error": "slow_down"},
            {"access_token": "atk", "token_type": "Bearer"},
        ]
    )
    sleep_durations: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        sleep_durations.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        flow = DeviceCodeFlow(
            http_client=client,
            display=_silent_display,
            poll_sleep=_record_sleep,
            slow_down_increment=5,
        )
        await flow.run(
            client_id="client-abc",
            scopes=["read"],
            authorization_endpoint="https://idp.example/authorize",
            token_endpoint="https://idp.example/token",
            device_authorization_endpoint="https://idp.example/device_authorization",
        )
    assert sleep_durations == [1.0, 6.0]  # second sleep is 1 + 5


@pytest.mark.asyncio
async def test_access_denied_raises() -> None:
    handler = _make_handler(token_payloads=[{"error": "access_denied"}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        flow = DeviceCodeFlow(
            http_client=client, display=_silent_display, poll_sleep=_instant_sleep
        )
        with pytest.raises(OAuthFlowError, match="access_denied"):
            await flow.run(
                client_id="client-abc",
                scopes=["read"],
                authorization_endpoint="https://idp.example/authorize",
                token_endpoint="https://idp.example/token",
                device_authorization_endpoint="https://idp.example/device_authorization",
            )


@pytest.mark.asyncio
async def test_expired_token_raises() -> None:
    handler = _make_handler(token_payloads=[{"error": "expired_token"}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        flow = DeviceCodeFlow(
            http_client=client, display=_silent_display, poll_sleep=_instant_sleep
        )
        with pytest.raises(OAuthFlowError, match="expired_token"):
            await flow.run(
                client_id="client-abc",
                scopes=["read"],
                authorization_endpoint="https://idp.example/authorize",
                token_endpoint="https://idp.example/token",
                device_authorization_endpoint="https://idp.example/device_authorization",
            )


@pytest.mark.asyncio
async def test_missing_device_endpoint_raises() -> None:
    flow = DeviceCodeFlow(display=_silent_display, poll_sleep=_instant_sleep)
    with pytest.raises(OAuthFlowError, match="device_authorization_endpoint"):
        await flow.run(
            client_id="client-abc",
            scopes=["read"],
            authorization_endpoint="https://idp.example/authorize",
            token_endpoint="https://idp.example/token",
        )


@pytest.mark.asyncio
async def test_display_receives_device_authorization() -> None:
    handler = _make_handler()
    received: list[DeviceAuthorization] = []

    def display(auth: DeviceAuthorization) -> None:
        received.append(auth)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        flow = DeviceCodeFlow(http_client=client, display=display, poll_sleep=_instant_sleep)
        await flow.run(
            client_id="client-abc",
            scopes=["read"],
            authorization_endpoint="https://idp.example/authorize",
            token_endpoint="https://idp.example/token",
            device_authorization_endpoint="https://idp.example/device_authorization",
        )
    assert len(received) == 1
    assert received[0].user_code == "ABCD-EFGH"
    assert received[0].verification_uri == "https://idp.example/device"
    assert received[0].verification_uri_complete is not None


@pytest.mark.asyncio
async def test_device_authorization_error_response_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_client"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        flow = DeviceCodeFlow(
            http_client=client, display=_silent_display, poll_sleep=_instant_sleep
        )
        with pytest.raises(OAuthFlowError, match="invalid_client"):
            await flow.run(
                client_id="client-abc",
                scopes=["read"],
                authorization_endpoint="https://idp.example/authorize",
                token_endpoint="https://idp.example/token",
                device_authorization_endpoint="https://idp.example/device_authorization",
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "reason"),
    [
        ("https://127.0.0.1/device_authorization", "loopback"),
        ("https://10.0.0.5/device_authorization", "private_network"),
        ("https://169.254.169.254/device_authorization", "metadata_service"),
    ],
)
async def test_device_authorization_endpoint_uses_url_safety(
    endpoint: str,
    reason: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected HTTP call to {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        flow = DeviceCodeFlow(
            http_client=client, display=_silent_display, poll_sleep=_instant_sleep
        )
        with pytest.raises(OAuthFlowError, match=reason):
            await flow.run(
                client_id="client-abc",
                scopes=["read"],
                authorization_endpoint="https://idp.example/authorize",
                token_endpoint="https://idp.example/token",
                device_authorization_endpoint=endpoint,
            )


@pytest.mark.asyncio
async def test_device_token_endpoint_uses_url_safety_after_authorization() -> None:
    handler = _make_handler()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        flow = DeviceCodeFlow(
            http_client=client, display=_silent_display, poll_sleep=_instant_sleep
        )
        with pytest.raises(OAuthFlowError, match="private_network"):
            await flow.run(
                client_id="client-abc",
                scopes=["read"],
                authorization_endpoint="https://idp.example/authorize",
                token_endpoint="https://10.0.0.5/token",
                device_authorization_endpoint="https://idp.example/device_authorization",
            )


@pytest.mark.asyncio
async def test_device_authorization_response_uses_size_cap() -> None:
    settings = KaosSecuritySettings(response_max_bytes=32)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "device_code": "D" * 64,
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://idp.example/device",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        flow = DeviceCodeFlow(
            http_client=client,
            display=_silent_display,
            poll_sleep=_instant_sleep,
            security_settings=settings,
        )
        with pytest.raises(OAuthFlowError, match="response size cap"):
            await flow.run(
                client_id="client-abc",
                scopes=["read"],
                authorization_endpoint="https://idp.example/authorize",
                token_endpoint="https://idp.example/token",
                device_authorization_endpoint="https://idp.example/device_authorization",
            )
