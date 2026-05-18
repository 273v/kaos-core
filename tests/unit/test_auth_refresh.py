"""Tests for ``kaos_core.auth.refresh.refresh_token``.

Uses ``httpx.MockTransport`` to simulate the IdP's token endpoint
without standing up a real server. Each test pins one part of the
refresh contract:

- Happy path: rotated refresh token, expires_at recomputed, issuer
  + client_id preserved.
- Server-omitted refresh_token: existing one carried forward.
- IdP error response: raises :class:`OAuthFlowError`.
- Non-JSON response: raises :class:`OAuthFlowError` with status.
- Missing metadata on the input token: raises
  :class:`OAuthFlowError` before any HTTP call.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from kaos_core.auth import OAuthFlowError, refresh_token
from kaos_core.config import OAuthToken
from kaos_core.security import KaosSecuritySettings


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _seed_token(**overrides: Any) -> OAuthToken:
    base: dict[str, Any] = {
        "access_token": SecretStr("old-access"),
        "token_type": "Bearer",
        "refresh_token": SecretStr("old-refresh"),
        "issuer": "https://idp.example/oauth/token",
        "client_id": "abc123",
        "expires_at": None,
        "scope": "read",
    }
    base.update(overrides)
    # If a caller passed a string instead of SecretStr, coerce.
    access_raw = base.get("access_token")
    if isinstance(access_raw, str):
        base["access_token"] = SecretStr(access_raw)
    refresh_raw = base.get("refresh_token")
    if isinstance(refresh_raw, str):
        base["refresh_token"] = SecretStr(refresh_raw)
    return OAuthToken(**base)


@pytest.mark.asyncio
async def test_happy_path_rotates_refresh_token() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["form"] = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "new-refresh",
                "scope": "read",
            },
        )

    async with _mock_client(handler) as client:
        new_token = await refresh_token(_seed_token(), client=client)

    assert seen["url"] == "https://idp.example/oauth/token"
    assert seen["form"]["grant_type"] == "refresh_token"
    assert seen["form"]["refresh_token"] == "old-refresh"
    assert seen["form"]["client_id"] == "abc123"

    assert new_token.access_token.get_secret_value() == "new-access"
    assert new_token.refresh_token is not None
    assert new_token.refresh_token.get_secret_value() == "new-refresh"
    assert new_token.issuer == "https://idp.example/oauth/token"
    assert new_token.client_id == "abc123"
    assert new_token.expires_at is not None  # populated from expires_in


@pytest.mark.asyncio
async def test_idp_omitting_refresh_token_keeps_old_one() -> None:
    """Some IdPs reuse the existing refresh_token; we must preserve it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    async with _mock_client(handler) as client:
        new_token = await refresh_token(_seed_token(), client=client)

    assert new_token.refresh_token is not None
    assert new_token.refresh_token.get_secret_value() == "old-refresh"


@pytest.mark.asyncio
async def test_idp_error_response_raises_oauth_flow_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "refresh token expired"},
        )

    async with _mock_client(handler) as client:
        with pytest.raises(OAuthFlowError, match="invalid_grant"):
            await refresh_token(_seed_token(), client=client)


@pytest.mark.asyncio
async def test_non_json_response_raises_oauth_flow_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="<html>internal error</html>")

    async with _mock_client(handler) as client:
        with pytest.raises(OAuthFlowError, match="not JSON"):
            await refresh_token(_seed_token(), client=client)


@pytest.mark.asyncio
async def test_missing_refresh_token_raises_without_http_call() -> None:
    token = _seed_token(refresh_token=None)
    with pytest.raises(OAuthFlowError, match="no refresh_token"):
        await refresh_token(token)


@pytest.mark.asyncio
async def test_missing_issuer_raises() -> None:
    token = _seed_token(issuer=None)
    with pytest.raises(OAuthFlowError, match="no issuer"):
        await refresh_token(token)


@pytest.mark.asyncio
async def test_missing_client_id_raises() -> None:
    token = _seed_token(client_id=None)
    with pytest.raises(OAuthFlowError, match="no client_id"):
        await refresh_token(token)


@pytest.mark.asyncio
async def test_token_response_carries_oauth_metadata() -> None:
    """Refreshed tokens must keep issuer + client_id so they're refreshable again."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "new",
                "token_type": "Bearer",
                "refresh_token": "new-refresh",
            },
        )

    async with _mock_client(handler) as client:
        new_token = await refresh_token(_seed_token(), client=client)

    assert new_token.issuer == "https://idp.example/oauth/token"
    assert new_token.client_id == "abc123"
    assert new_token.obtained_at is not None
    # And the new token, in turn, can be refreshed again — issuer
    # and client_id propagate.
    second_handler_form: dict[str, str] = {}

    def handler2(request: httpx.Request) -> httpx.Response:
        nonlocal second_handler_form
        second_handler_form = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "access_token": "newer",
                "token_type": "Bearer",
                "refresh_token": "newer-refresh",
            },
        )

    async with _mock_client(handler2) as client2:
        await refresh_token(new_token, client=client2)

    assert second_handler_form["refresh_token"] == "new-refresh"


@pytest.mark.asyncio
async def test_no_client_supplied_uses_managed_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caller can omit ``client``; refresh_token spins up its own."""
    # Patch httpx.AsyncClient to verify it's called with no args.
    real_async_client = httpx.AsyncClient

    constructed: list[Any] = []

    class _Spy(real_async_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(
                *args,
                **kwargs,
                transport=httpx.MockTransport(
                    lambda req: httpx.Response(
                        200, json={"access_token": "ok", "token_type": "Bearer"}
                    )
                ),
            )
            constructed.append((args, kwargs))

    monkeypatch.setattr(httpx, "AsyncClient", _Spy)
    new_token = await refresh_token(_seed_token())
    assert new_token.access_token.get_secret_value() == "ok"
    assert len(constructed) == 1


@pytest.mark.asyncio
async def test_response_with_explicit_error_field_raises() -> None:
    """Even if the IdP returns 200, an error field in the body raises."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"error": "server_error"}).encode("utf-8"))

    async with _mock_client(handler) as client:
        with pytest.raises(OAuthFlowError, match="server_error"):
            await refresh_token(_seed_token(), client=client)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("issuer", "reason"),
    [
        ("https://127.0.0.1/oauth/token", "loopback"),
        ("https://10.0.0.5/oauth/token", "private_network"),
        ("https://169.254.169.254/oauth/token", "metadata_service"),
    ],
)
async def test_refresh_token_endpoint_uses_url_safety(issuer: str, reason: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected HTTP call to {request.url}")

    async with _mock_client(handler) as client:
        with pytest.raises(OAuthFlowError, match=reason):
            await refresh_token(_seed_token(issuer=issuer), client=client)


@pytest.mark.asyncio
async def test_refresh_response_uses_size_cap() -> None:
    settings = KaosSecuritySettings(response_max_bytes=32)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "a" * 64, "token_type": "Bearer"},
        )

    async with _mock_client(handler) as client:
        with pytest.raises(OAuthFlowError, match="response size cap"):
            await refresh_token(_seed_token(), client=client, security_settings=settings)
