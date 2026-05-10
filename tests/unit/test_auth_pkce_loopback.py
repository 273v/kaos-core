"""End-to-end test for ``PKCELoopbackFlow``.

Drives a complete flow:

1. Capture the authorization URL the runner would open in a browser
   (via the ``open_browser`` injection point).
2. After capture, simulate the IdP's redirect back to the runner's
   loopback callback by issuing an HTTP GET to the captured
   ``redirect_uri`` with ``code`` + ``state`` query parameters.
3. The runner exchanges the ``code`` for tokens at the (mocked)
   token endpoint via the injected ``http_client``.

The token endpoint is mocked with :class:`httpx.MockTransport` so
no real network traffic happens.
"""

from __future__ import annotations

import asyncio
import urllib.parse
from typing import Any

import httpx
import pytest

from kaos_core.auth import OAuthFlowError, PKCELoopbackFlow


@pytest.mark.asyncio
async def test_full_flow_completes() -> None:
    captured_url: list[str] = []

    def fake_open(url: str) -> bool:
        captured_url.append(url)
        return True

    seen_token_form: dict[str, str] = {}

    def token_handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_token_form
        seen_token_form = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "access_token": "atk",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "rtk",
                "scope": "read write",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(token_handler)) as client:
        flow = PKCELoopbackFlow(
            open_browser=fake_open,
            http_client=client,
            timeout_seconds=10.0,
        )

        async def _send_callback() -> None:
            # Wait for the runner to start the loopback server and
            # call open_browser. We poll captured_url; the URL
            # carries the redirect_uri + state we need to replay.
            for _ in range(50):
                if captured_url:
                    break
                await asyncio.sleep(0.01)
            assert captured_url, "open_browser was never called"
            url = captured_url[0]
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            redirect_uri = params["redirect_uri"]
            state = params["state"]
            # Hit the loopback callback as the IdP would.
            async with httpx.AsyncClient() as cb_client:
                await cb_client.get(redirect_uri, params={"code": "auth-code", "state": state})

        runner = asyncio.create_task(
            flow.run(
                client_id="client-abc",
                scopes=["read", "write"],
                authorization_endpoint="https://idp.example/authorize",
                token_endpoint="https://idp.example/token",
            )
        )
        callback = asyncio.create_task(_send_callback())
        token, _ = await asyncio.gather(runner, callback)

    # Token endpoint received the right form.
    assert seen_token_form["grant_type"] == "authorization_code"
    assert seen_token_form["code"] == "auth-code"
    assert seen_token_form["client_id"] == "client-abc"
    assert "code_verifier" in seen_token_form
    # Token populated correctly.
    assert token.access_token.get_secret_value() == "atk"
    assert token.refresh_token is not None
    assert token.refresh_token.get_secret_value() == "rtk"
    assert token.issuer == "https://idp.example/token"
    assert token.client_id == "client-abc"


@pytest.mark.asyncio
async def test_state_mismatch_rejected() -> None:
    captured_url: list[str] = []

    def fake_open(url: str) -> bool:
        captured_url.append(url)
        return True

    def token_handler(request: httpx.Request) -> httpx.Response:
        # Should never reach the token endpoint.
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(token_handler)) as client:
        flow = PKCELoopbackFlow(open_browser=fake_open, http_client=client, timeout_seconds=5.0)

        async def _send_bad_callback() -> None:
            for _ in range(50):
                if captured_url:
                    break
                await asyncio.sleep(0.01)
            url = captured_url[0]
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            redirect_uri = params["redirect_uri"]
            async with httpx.AsyncClient() as cb_client:
                # Wrong state — runner should reject.
                await cb_client.get(redirect_uri, params={"code": "auth-code", "state": "WRONG"})

        runner = asyncio.create_task(
            flow.run(
                client_id="client-abc",
                scopes=["read"],
                authorization_endpoint="https://idp.example/authorize",
                token_endpoint="https://idp.example/token",
            )
        )
        callback = asyncio.create_task(_send_bad_callback())
        with pytest.raises(OAuthFlowError, match="state mismatch"):
            await asyncio.gather(runner, callback)


@pytest.mark.asyncio
async def test_idp_error_in_callback() -> None:
    captured_url: list[str] = []

    def fake_open(url: str) -> bool:
        captured_url.append(url)
        return True

    def token_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(token_handler)) as client:
        flow = PKCELoopbackFlow(open_browser=fake_open, http_client=client, timeout_seconds=5.0)

        async def _send_error_callback() -> None:
            for _ in range(50):
                if captured_url:
                    break
                await asyncio.sleep(0.01)
            url = captured_url[0]
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            redirect_uri = params["redirect_uri"]
            async with httpx.AsyncClient() as cb_client:
                await cb_client.get(
                    redirect_uri,
                    params={"error": "access_denied", "state": params["state"]},
                )

        runner = asyncio.create_task(
            flow.run(
                client_id="client-abc",
                scopes=["read"],
                authorization_endpoint="https://idp.example/authorize",
                token_endpoint="https://idp.example/token",
            )
        )
        callback = asyncio.create_task(_send_error_callback())
        with pytest.raises(OAuthFlowError, match="access_denied"):
            await asyncio.gather(runner, callback)


@pytest.mark.asyncio
async def test_authorization_url_includes_pkce_params() -> None:
    captured_url: list[str] = []

    def fake_open(url: str) -> bool:
        captured_url.append(url)
        return True

    def token_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "atk", "token_type": "Bearer"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(token_handler)) as client:
        flow = PKCELoopbackFlow(open_browser=fake_open, http_client=client, timeout_seconds=5.0)

        async def _send_callback() -> None:
            for _ in range(50):
                if captured_url:
                    break
                await asyncio.sleep(0.01)
            url = captured_url[0]
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            redirect_uri = params["redirect_uri"]
            state = params["state"]
            async with httpx.AsyncClient() as cb_client:
                await cb_client.get(redirect_uri, params={"code": "auth-code", "state": state})

        runner = asyncio.create_task(
            flow.run(
                client_id="client-abc",
                scopes=["read"],
                authorization_endpoint="https://idp.example/authorize",
                token_endpoint="https://idp.example/token",
            )
        )
        callback = asyncio.create_task(_send_callback())
        await asyncio.gather(runner, callback)

    parsed = urllib.parse.urlparse(captured_url[0])
    params: dict[str, Any] = dict(urllib.parse.parse_qsl(parsed.query))
    assert params["response_type"] == "code"
    assert params["client_id"] == "client-abc"
    assert params["scope"] == "read"
    assert params["code_challenge_method"] == "S256"
    assert len(params["code_challenge"]) >= 43  # base64url(sha256) without padding
    assert len(params["state"]) >= 16
    assert params["redirect_uri"].startswith("http://127.0.0.1:")
    assert params["redirect_uri"].endswith("/callback")
