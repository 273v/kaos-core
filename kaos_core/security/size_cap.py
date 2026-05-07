"""HTTP response size caps — pre-flight Content-Length check + streaming guard.

Two enforcement points:

1. **Pre-flight** — :func:`check_content_length` reads the ``Content-Length``
   response header and rejects oversize responses *before* any body is read.
   Cheapest layer; catches the well-behaved-but-large case.

2. **Streaming** — :func:`read_capped_bytes` accumulates chunks from
   ``response.aiter_bytes()`` against a running budget and raises as soon as
   the budget is exceeded. Catches malformed/missing ``Content-Length`` and
   chunked-transfer responses that lie about their size.

Use streaming whenever possible (``async with client.stream("GET", url) as resp``).
For already-loaded responses (the common ``resp = await client.get(url)`` shape),
:func:`cap_loaded_bytes` is a post-hoc check on ``resp.content`` — it can detect
a bomb but not prevent the OOM that loading it caused. Path is documented as
second-best in the migration notes.

The protocol is duck-typed: anything with a ``headers`` mapping and an
``aiter_bytes(chunk_size)`` async iterator works. No ``httpx`` import here, so
this module remains compatible with ``aiohttp``, mocks, and whatever transport
the caller picked.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol, runtime_checkable

from kaos_core.exceptions import ResponseSizeError
from kaos_core.security.settings import KaosSecuritySettings


@runtime_checkable
class _AsyncResponseLike(Protocol):
    """Minimal duck-typed async response (compatible with ``httpx.Response``)."""

    headers: Mapping[str, str]

    def aiter_bytes(self, chunk_size: int = ...) -> AsyncIterator[bytes]: ...


def _resolve_max_bytes(
    max_bytes: int | None, settings: KaosSecuritySettings | None
) -> tuple[int, KaosSecuritySettings]:
    if settings is None:
        settings = KaosSecuritySettings()
    if max_bytes is None:
        max_bytes = settings.response_max_bytes
    if max_bytes <= 0:
        raise ValueError(f"max_bytes must be positive, got {max_bytes}")
    return max_bytes, settings


def check_content_length(
    headers: Mapping[str, str],
    *,
    max_bytes: int | None = None,
    settings: KaosSecuritySettings | None = None,
) -> None:
    """Pre-flight: raise :class:`ResponseSizeError` if ``Content-Length`` exceeds the cap.

    Silent on missing or unparseable ``Content-Length`` — the streaming guard
    is responsible for the chunked-transfer / lying-server case.

    Args:
        headers: Mapping of response headers (case-insensitive lookup tried).
        max_bytes: Override the settings cap.
        settings: Override the env-derived defaults.
    """
    max_bytes, _ = _resolve_max_bytes(max_bytes, settings)
    cl = headers.get("content-length")
    if cl is None:
        cl = headers.get("Content-Length")
    if cl is None:
        return
    try:
        declared = int(cl)
    except (ValueError, TypeError):
        return
    if declared > max_bytes:
        raise ResponseSizeError(max_bytes=max_bytes, content_length=declared)


def cap_loaded_bytes(
    content: bytes,
    *,
    max_bytes: int | None = None,
    settings: KaosSecuritySettings | None = None,
) -> None:
    """Post-hoc: raise :class:`ResponseSizeError` if ``content`` is larger than the cap.

    Use with already-loaded responses (``resp.content`` after ``client.get(url)``).
    This cannot prevent the OOM that loading the body caused; prefer the
    streaming path (:func:`read_capped_bytes`) for new code.
    """
    max_bytes, _ = _resolve_max_bytes(max_bytes, settings)
    if len(content) > max_bytes:
        raise ResponseSizeError(max_bytes=max_bytes, seen_bytes=len(content))


async def read_capped_bytes(
    response: _AsyncResponseLike,
    *,
    max_bytes: int | None = None,
    settings: KaosSecuritySettings | None = None,
    chunk_size: int = 65_536,
) -> bytes:
    """Read ``response`` body with a hard byte budget.

    Caller should be using a streaming response context (e.g. httpx's
    ``async with client.stream(...) as resp:``) so the body has not been
    auto-loaded. Both layers fire when their respective settings flag is on:

    * pre-flight ``Content-Length`` check (:attr:`KaosSecuritySettings
      .response_size_check_via_content_length`)
    * streaming budget on ``aiter_bytes`` (:attr:`KaosSecuritySettings
      .response_size_check_via_streaming`)

    If both flags are off the function still reads the body but performs no
    enforcement (it just becomes a thin wrapper around ``aiter_bytes``).
    """
    max_bytes, resolved = _resolve_max_bytes(max_bytes, settings)

    if resolved.response_size_check_via_content_length:
        check_content_length(response.headers, max_bytes=max_bytes)

    if not resolved.response_size_check_via_streaming:
        chunks: list[bytes] = []
        async for chunk in response.aiter_bytes(chunk_size):
            chunks.append(chunk)
        return b"".join(chunks)

    buf = bytearray()
    async for chunk in response.aiter_bytes(chunk_size):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise ResponseSizeError(max_bytes=max_bytes, seen_bytes=len(buf))
    return bytes(buf)


async def read_capped_json(
    response: _AsyncResponseLike,
    *,
    max_bytes: int | None = None,
    settings: KaosSecuritySettings | None = None,
) -> Any:
    """Convenience: :func:`read_capped_bytes` followed by ``json.loads``.

    Raises :class:`ResponseSizeError` from the size check (before JSON parse)
    and propagates any ``json.JSONDecodeError`` unchanged.
    """
    body = await read_capped_bytes(response, max_bytes=max_bytes, settings=settings)
    return json.loads(body)
