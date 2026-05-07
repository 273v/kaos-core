"""Unit tests for kaos_core.security.size_cap — Content-Length + streaming guards."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping

import pytest

from kaos_core.exceptions import ResponseSizeError
from kaos_core.security import (
    KaosSecuritySettings,
    cap_loaded_bytes,
    check_content_length,
    read_capped_bytes,
    read_capped_json,
)


class FakeResponse:
    """Minimal duck-typed httpx.Response stand-in.

    Holds a ``body`` plus an optional ``headers`` mapping. ``aiter_bytes``
    yields the body in fixed-size chunks; the ``lying`` flag lets us
    simulate a server that misreports Content-Length.
    """

    def __init__(
        self,
        body: bytes,
        *,
        content_length: int | str | None = "auto",
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        self.body = body
        if content_length == "auto":
            cl: str | None = str(len(body))
        elif content_length is None:
            cl = None
        else:
            cl = str(content_length)
        h: dict[str, str] = {}
        if cl is not None:
            h["content-length"] = cl
        if extra_headers:
            h.update(extra_headers)
        self.headers: Mapping[str, str] = h

    async def aiter_bytes(self, chunk_size: int = 8192) -> AsyncIterator[bytes]:
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i : i + chunk_size]


# ---------------------------------------------------------------------------
# check_content_length — pre-flight
# ---------------------------------------------------------------------------


class TestCheckContentLength:
    def test_under_cap_passes(self) -> None:
        check_content_length({"content-length": "100"}, max_bytes=1000)

    def test_over_cap_raises(self) -> None:
        with pytest.raises(ResponseSizeError) as excinfo:
            check_content_length({"content-length": "2000"}, max_bytes=1000)
        assert excinfo.value.max_bytes == 1000
        assert excinfo.value.content_length == 2000
        assert excinfo.value.seen_bytes is None

    def test_missing_header_silent(self) -> None:
        check_content_length({}, max_bytes=1000)

    def test_unparseable_header_silent(self) -> None:
        check_content_length({"content-length": "not-a-number"}, max_bytes=1000)

    def test_case_insensitive_header(self) -> None:
        # httpx headers are case-insensitive but a generic Mapping isn't.
        # We try both spellings.
        with pytest.raises(ResponseSizeError):
            check_content_length({"Content-Length": "2000"}, max_bytes=1000)

    def test_uses_settings_default_when_no_max(self) -> None:
        settings = KaosSecuritySettings(response_max_bytes=500)
        with pytest.raises(ResponseSizeError):
            check_content_length({"content-length": "1000"}, settings=settings)

    def test_at_cap_exactly_passes(self) -> None:
        # Boundary case: declared == cap should pass (the cap is "exceeds").
        check_content_length({"content-length": "1000"}, max_bytes=1000)


# ---------------------------------------------------------------------------
# cap_loaded_bytes — post-hoc
# ---------------------------------------------------------------------------


class TestCapLoadedBytes:
    def test_under_cap_passes(self) -> None:
        cap_loaded_bytes(b"x" * 100, max_bytes=1000)

    def test_over_cap_raises(self) -> None:
        with pytest.raises(ResponseSizeError) as excinfo:
            cap_loaded_bytes(b"x" * 2000, max_bytes=1000)
        assert excinfo.value.max_bytes == 1000
        assert excinfo.value.seen_bytes == 2000
        assert excinfo.value.content_length is None

    def test_at_cap_exactly_passes(self) -> None:
        cap_loaded_bytes(b"x" * 1000, max_bytes=1000)

    def test_uses_settings_default(self) -> None:
        settings = KaosSecuritySettings(response_max_bytes=500)
        with pytest.raises(ResponseSizeError):
            cap_loaded_bytes(b"x" * 1000, settings=settings)


# ---------------------------------------------------------------------------
# read_capped_bytes — streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReadCappedBytes:
    async def test_small_body_with_content_length(self) -> None:
        resp = FakeResponse(b"hello world", content_length="auto")
        body = await read_capped_bytes(resp, max_bytes=1000)
        assert body == b"hello world"

    async def test_small_body_without_content_length(self) -> None:
        resp = FakeResponse(b"hello world", content_length=None)
        body = await read_capped_bytes(resp, max_bytes=1000)
        assert body == b"hello world"

    async def test_content_length_over_cap_blocked_preflight(self) -> None:
        resp = FakeResponse(b"x" * 2000, content_length="auto")
        with pytest.raises(ResponseSizeError) as excinfo:
            await read_capped_bytes(resp, max_bytes=1000)
        # content_length set means pre-flight caught it
        assert excinfo.value.content_length == 2000
        assert excinfo.value.seen_bytes is None

    async def test_lying_content_length_caught_streaming(self) -> None:
        # Server says 100 bytes, actually 2000 — pre-flight passes,
        # streaming guard catches it.
        resp = FakeResponse(b"x" * 2000, content_length=100)
        with pytest.raises(ResponseSizeError) as excinfo:
            await read_capped_bytes(resp, max_bytes=1000)
        assert excinfo.value.seen_bytes is not None
        assert excinfo.value.seen_bytes > 1000

    async def test_no_content_length_oversize_caught_streaming(self) -> None:
        # Chunked transfer / no Content-Length, oversize body.
        resp = FakeResponse(b"x" * 2000, content_length=None)
        with pytest.raises(ResponseSizeError):
            await read_capped_bytes(resp, max_bytes=1000)

    async def test_streaming_check_disabled(self) -> None:
        # If both checks are off, oversize body is silently read.
        settings = KaosSecuritySettings(
            response_size_check_via_content_length=False,
            response_size_check_via_streaming=False,
            response_max_bytes=1000,
        )
        resp = FakeResponse(b"x" * 2000, content_length=None)
        body = await read_capped_bytes(resp, settings=settings)
        assert body == b"x" * 2000

    async def test_only_content_length_check(self) -> None:
        # Pre-flight only: lying server sneaks past.
        settings = KaosSecuritySettings(
            response_size_check_via_content_length=True,
            response_size_check_via_streaming=False,
            response_max_bytes=1000,
        )
        resp = FakeResponse(b"x" * 2000, content_length=100)
        body = await read_capped_bytes(resp, settings=settings)
        assert len(body) == 2000

    async def test_uses_settings_default_max_bytes(self) -> None:
        settings = KaosSecuritySettings(response_max_bytes=500)
        resp = FakeResponse(b"x" * 1000, content_length="auto")
        with pytest.raises(ResponseSizeError):
            await read_capped_bytes(resp, settings=settings)

    async def test_invalid_max_bytes(self) -> None:
        resp = FakeResponse(b"hi")
        with pytest.raises(ValueError):
            await read_capped_bytes(resp, max_bytes=0)
        with pytest.raises(ValueError):
            await read_capped_bytes(resp, max_bytes=-1)


# ---------------------------------------------------------------------------
# read_capped_json — convenience
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReadCappedJson:
    async def test_valid_json(self) -> None:
        body = json.dumps({"key": "value", "n": 42}).encode()
        resp = FakeResponse(body, content_length="auto")
        data = await read_capped_json(resp, max_bytes=1000)
        assert data == {"key": "value", "n": 42}

    async def test_oversize_caught_before_parse(self) -> None:
        body = json.dumps({"x": "y" * 5000}).encode()
        resp = FakeResponse(body, content_length="auto")
        with pytest.raises(ResponseSizeError):
            await read_capped_json(resp, max_bytes=1000)

    async def test_malformed_json_propagates(self) -> None:
        resp = FakeResponse(b"not valid json", content_length="auto")
        with pytest.raises(json.JSONDecodeError):
            await read_capped_json(resp, max_bytes=1000)
