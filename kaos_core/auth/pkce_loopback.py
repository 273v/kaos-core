"""RFC 7636 + RFC 8252 §7.3 — PKCE flow with 127.0.0.1 loopback redirect.

The classic OAuth flow for native desktop apps:

1. Generate a high-entropy ``code_verifier`` and the matching
   ``code_challenge = base64url(sha256(verifier))``.
2. Bind ``127.0.0.1`` on a random port in the IANA dynamic range
   ``[49152, 65535]`` (RFC 6335 §6).
3. Open the browser to the IdP's ``authorization_endpoint`` with
   ``response_type=code``, ``code_challenge=...``,
   ``code_challenge_method=S256``,
   ``redirect_uri=http://127.0.0.1:{port}/callback``, and a random
   ``state`` we'll verify on return.
4. The IdP redirects the browser back to our loopback handler with
   ``code`` and ``state`` query parameters; we verify state and
   exchange the code at the ``token_endpoint``.

Injection points (all keyword-only, defaults sane for production):

- ``open_browser`` — replaces ``webbrowser.open``. Useful for
  tests (record what URL would be opened without actually opening
  a browser) and for runtimes that prefer a custom browser
  launcher.
- ``http_client`` — pre-configured :class:`httpx.AsyncClient`.
  Useful for tests with ``httpx.MockTransport``.
- ``port_range`` — narrow the loopback bind range, e.g. for
  enterprise firewall allowlisting.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import socket
import urllib.parse
import webbrowser
from collections.abc import Callable, Coroutine, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from kaos_core.auth._token_response import parse_token_response
from kaos_core.auth.errors import OAuthFlowError
from kaos_core.logging import get_logger

if TYPE_CHECKING:
    import httpx

    from kaos_core.config.auth import OAuthToken

logger = get_logger(__name__)

# Browser-facing HTML shown after the OAuth callback. Plain ASCII so
# any embedded server can serve it without charset negotiation.
_CALLBACK_BODY_OK = (
    "<!doctype html><html><head><title>kaos-core: signed in</title></head>"
    "<body style='font-family:sans-serif;padding:2em;'>"
    "<h2>Signed in.</h2>"
    "<p>You can close this tab and return to your terminal.</p>"
    "</body></html>"
)
_CALLBACK_BODY_ERR = (
    "<!doctype html><html><head><title>kaos-core: error</title></head>"
    "<body style='font-family:sans-serif;padding:2em;'>"
    "<h2>Authorization failed.</h2>"
    "<p>Return to your terminal for details.</p>"
    "</body></html>"
)

OpenBrowserCallable = Callable[[str], bool]


def _default_open_browser(url: str) -> bool:
    return webbrowser.open(url, new=2)


@dataclass
class PKCELoopbackFlow:
    """RFC 8252 §7.3 PKCE + loopback flow runner.

    Args:
        port_range: ``(low, high)`` inclusive port range for the
            loopback bind. Default is the IANA dynamic range
            ``[49152, 65535]`` (RFC 6335).
        callback_path: URL path the IdP should redirect to. Default
            ``/callback`` is conventional; some IdPs allowlist
            specific paths and need this overridden.
        timeout_seconds: How long to wait for the browser callback
            before giving up. Default 5 minutes.
        open_browser: Function that opens the authorization URL in
            a browser. Default uses :func:`webbrowser.open`.
            Tests inject a recording fake.
        http_client: Pre-configured :class:`httpx.AsyncClient`.
            Tests inject one with :class:`httpx.MockTransport`.
    """

    port_range: tuple[int, int] = (49152, 65535)
    callback_path: str = "/callback"
    timeout_seconds: float = 300.0
    open_browser: OpenBrowserCallable = _default_open_browser
    http_client: httpx.AsyncClient | None = None

    async def run(
        self,
        *,
        client_id: str,
        scopes: Sequence[str],
        authorization_endpoint: str,
        token_endpoint: str,
        device_authorization_endpoint: str | None = None,
    ) -> OAuthToken:
        del device_authorization_endpoint  # not used; kept for AuthFlow Protocol

        verifier = _make_code_verifier()
        challenge = _make_code_challenge(verifier)
        state = secrets.token_urlsafe(16)

        port = _bind_random_port(self.port_range)
        redirect_uri = f"http://127.0.0.1:{port}{self.callback_path}"

        auth_url = _build_authorization_url(
            authorization_endpoint,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=scopes,
            state=state,
            code_challenge=challenge,
        )

        # Run the loopback server and the browser-open in tandem.
        callback_future: asyncio.Future[dict[str, str]] = asyncio.get_event_loop().create_future()
        server = await asyncio.start_server(
            _make_callback_handler(callback_future), "127.0.0.1", port
        )

        try:
            opened = self.open_browser(auth_url)
            if not opened:
                logger.warning("Browser failed to open. Visit this URL manually:\n  %s", auth_url)
            params = await asyncio.wait_for(callback_future, timeout=self.timeout_seconds)
        except TimeoutError as exc:
            msg = (
                f"PKCE loopback callback timed out after {self.timeout_seconds:.0f}s. "
                "Did the user complete the browser sign-in?"
            )
            raise OAuthFlowError(msg) from exc
        finally:
            server.close()
            with suppress(Exception):
                await server.wait_closed()

        if params.get("state") != state:
            msg = "PKCE callback state mismatch — possible CSRF; refusing to exchange code"
            raise OAuthFlowError(msg)
        if "error" in params:
            msg = (
                f"IdP returned OAuth error in callback: {params['error']}"
                f"{': ' + params['error_description'] if 'error_description' in params else ''}"
            )
            raise OAuthFlowError(msg)
        code = params.get("code")
        if not code:
            msg = "PKCE callback did not include 'code'"
            raise OAuthFlowError(msg)

        return await self._exchange_code(
            code=code,
            verifier=verifier,
            redirect_uri=redirect_uri,
            client_id=client_id,
            token_endpoint=token_endpoint,
        )

    async def _exchange_code(
        self,
        *,
        code: str,
        verifier: str,
        redirect_uri: str,
        client_id: str,
        token_endpoint: str,
    ) -> OAuthToken:
        import httpx

        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        }

        async def _post(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(token_endpoint, data=form, timeout=self.timeout_seconds)

        if self.http_client is None:
            async with httpx.AsyncClient() as managed_client:
                response = await _post(managed_client)
        else:
            response = await _post(self.http_client)

        try:
            payload = response.json()
        except ValueError as exc:
            msg = (
                f"Token endpoint {token_endpoint} returned non-JSON (status {response.status_code})"
            )
            raise OAuthFlowError(msg) from exc

        return parse_token_response(payload, issuer=token_endpoint, client_id=client_id)


# ──────────────── helpers ────────────────


def _make_code_verifier() -> str:
    """Generate a 128-character URL-safe code_verifier (RFC 7636 §4.1)."""
    # 96 random bytes → 128 base64url-no-pad chars (within RFC range 43-128).
    return base64.urlsafe_b64encode(secrets.token_bytes(96)).rstrip(b"=").decode("ascii")


def _make_code_challenge(verifier: str) -> str:
    """RFC 7636 §4.2 S256 code_challenge."""
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )


def _bind_random_port(port_range: tuple[int, int]) -> int:
    """Bind 127.0.0.1 on a port within *port_range*; return the port.

    The socket is closed before returning — there's an unavoidable
    race between this probe and ``asyncio.start_server`` reclaiming
    the port; in practice it doesn't matter because nothing else on
    the box is grabbing dynamic-range ports synchronously. We
    iterate up to a small bounded retry budget to stay robust under
    contention.
    """
    low, high = port_range
    for _ in range(10):
        port = secrets.randbelow(high - low + 1) + low
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", port))
        except OSError:
            continue
        return port
    msg = f"Could not bind a loopback port in {port_range} after 10 tries"
    raise OAuthFlowError(msg)


def _build_authorization_url(
    endpoint: str,
    *,
    client_id: str,
    redirect_uri: str,
    scopes: Sequence[str],
    state: str,
    code_challenge: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    parsed = urllib.parse.urlparse(endpoint)
    existing = urllib.parse.parse_qsl(parsed.query)
    merged = urllib.parse.urlencode([*existing, *params.items()])
    return urllib.parse.urlunparse(parsed._replace(query=merged))


def _make_callback_handler(
    future: asyncio.Future[dict[str, str]],
) -> Callable[[asyncio.StreamReader, asyncio.StreamWriter], Coroutine[Any, Any, None]]:
    """Build an asyncio stream handler that fulfills *future* on first request."""

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = (await reader.readline()).decode("ascii", errors="replace")
            # Drain headers — we don't need them but the client will
            # block sending the body until we accept it.
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b""):
                    break
            parts = request_line.split(" ")
            if len(parts) < 2:
                params: dict[str, str] = {}
            else:
                _method, path, *_rest = parts
                parsed = urllib.parse.urlparse(path)
                params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
            body = _CALLBACK_BODY_ERR if "error" in params else _CALLBACK_BODY_OK
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n"
                "\r\n"
                f"{body}"
            ).encode("ascii")
            writer.write(response)
            await writer.drain()
            if not future.done():
                future.set_result(params)
        except (ConnectionError, OSError):
            if not future.done():
                future.set_exception(OAuthFlowError("Loopback callback connection failed"))
        finally:
            with suppress(Exception):
                writer.close()
                await writer.wait_closed()

    return _handle


__all__ = ["PKCELoopbackFlow"]
