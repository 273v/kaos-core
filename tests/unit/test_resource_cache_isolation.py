"""Cross-context cache-isolation tests for ResourceRegistry.

The previous registry cached every read result by URI alone, which
allowed a context-aware resource (one whose ``read()`` inspects the
context, e.g. returning ``context.session_id``) to leak the first
caller's data to every subsequent caller in a different context.

These tests pin the new contract:

- Default (``cache_scope = "per-session"``): cache is keyed on
  ``(uri, context.session_id)``. Different sessions never see each
  other's cached values.
- ``cache_scope = "global"``: caller asserts the resource is
  context-independent; the registry caches by URI alone.
- ``cache_scope = "none"``: the registry never caches; every call
  re-runs ``read()``.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from kaos_core import (
    KaosContext,
    KaosResource,
    KaosRuntime,
    ResourceMetadata,
    ResourceType,
)
from kaos_core.base.resource import CacheScope


class _CtxAwareResource(KaosResource):
    """Returns context.session_id; default per-session cache."""

    def __init__(self) -> None:
        super().__init__()
        self.read_count = 0

    @property
    def metadata(self) -> ResourceMetadata:
        return ResourceMetadata(
            uri="kaos://test/per-session",
            name="per-session",
            description="A context-aware test resource (default cache_scope).",
            resource_type=ResourceType.DOCUMENT,
            provider_module="kaos-core",
            version="0.1.0",
        )

    async def read(self, context: KaosContext | None = None) -> Any:
        self.read_count += 1
        return {"session_id": context.session_id if context else None}

    async def get_metadata(self, context: KaosContext | None = None) -> dict[str, Any]:
        return {"kind": "per-session"}


class _GlobalResource(KaosResource):
    """A resource that is provably context-independent — opts into a
    global cache so multiple sessions share one entry."""

    cache_scope: ClassVar[CacheScope] = "global"

    def __init__(self) -> None:
        super().__init__()
        self.read_count = 0

    @property
    def metadata(self) -> ResourceMetadata:
        return ResourceMetadata(
            uri="kaos://test/global",
            name="global",
            description="A context-independent test resource.",
            resource_type=ResourceType.DOCUMENT,
            provider_module="kaos-core",
            version="0.1.0",
        )

    async def read(self, context: KaosContext | None = None) -> Any:
        self.read_count += 1
        return {"static": True}

    async def get_metadata(self, context: KaosContext | None = None) -> dict[str, Any]:
        return {"kind": "global"}


class _NoCacheResource(KaosResource):
    cache_scope: ClassVar[CacheScope] = "none"

    def __init__(self) -> None:
        super().__init__()
        self.read_count = 0

    @property
    def metadata(self) -> ResourceMetadata:
        return ResourceMetadata(
            uri="kaos://test/none",
            name="none",
            description="A resource that opts out of caching.",
            resource_type=ResourceType.DOCUMENT,
            provider_module="kaos-core",
            version="0.1.0",
        )

    async def read(self, context: KaosContext | None = None) -> Any:
        self.read_count += 1
        return {"call": self.read_count}

    async def get_metadata(self, context: KaosContext | None = None) -> dict[str, Any]:
        return {"kind": "none"}


@pytest.fixture
def runtime() -> KaosRuntime:
    return KaosRuntime()


def _ctx(rt: KaosRuntime, session_id: str) -> KaosContext:
    return KaosContext.create(session_id=session_id, runtime=rt)


# ────────────────────────────────────────────────────────────────────
# Per-session (default) — different sessions get different cache entries
# ────────────────────────────────────────────────────────────────────


async def test_per_session_cache_does_not_leak_between_sessions(
    runtime: KaosRuntime,
) -> None:
    resource = _CtxAwareResource()
    runtime.resources.register_resource(resource)

    # First read by s1: read_count goes from 0 -> 1, cache populated for s1.
    s1_first = await runtime.resources.get_resource(
        "kaos://test/per-session", context=_ctx(runtime, "s1")
    )
    assert s1_first == {"session_id": "s1"}
    assert resource.read_count == 1

    # Same session reads again — served from cache.
    s1_second = await runtime.resources.get_resource(
        "kaos://test/per-session", context=_ctx(runtime, "s1")
    )
    assert s1_second == {"session_id": "s1"}
    assert resource.read_count == 1, "second same-session read must hit cache"

    # Different session must NOT receive s1's cached value.
    s2_first = await runtime.resources.get_resource(
        "kaos://test/per-session", context=_ctx(runtime, "s2")
    )
    assert s2_first == {"session_id": "s2"}, (
        "session s2 received session s1's cached value — cache leak"
    )
    assert resource.read_count == 2

    # Two distinct cache entries exist.
    assert runtime.resources.get_stats()["cached_entries"] == 2


# ────────────────────────────────────────────────────────────────────
# Global — opt-in, shared across sessions
# ────────────────────────────────────────────────────────────────────


async def test_global_scope_shares_cache_across_sessions(
    runtime: KaosRuntime,
) -> None:
    resource = _GlobalResource()
    runtime.resources.register_resource(resource)

    await runtime.resources.get_resource("kaos://test/global", context=_ctx(runtime, "s1"))
    await runtime.resources.get_resource("kaos://test/global", context=_ctx(runtime, "s2"))
    await runtime.resources.get_resource("kaos://test/global", context=_ctx(runtime, "s3"))

    # The resource was read exactly once; subsequent calls hit the
    # shared global cache regardless of session_id.
    assert resource.read_count == 1
    assert runtime.resources.get_stats()["cached_entries"] == 1


# ────────────────────────────────────────────────────────────────────
# None — never cache
# ────────────────────────────────────────────────────────────────────


async def test_none_scope_skips_cache_entirely(runtime: KaosRuntime) -> None:
    resource = _NoCacheResource()
    runtime.resources.register_resource(resource)

    a = await runtime.resources.get_resource("kaos://test/none", context=_ctx(runtime, "s1"))
    b = await runtime.resources.get_resource("kaos://test/none", context=_ctx(runtime, "s1"))
    c = await runtime.resources.get_resource("kaos://test/none", context=_ctx(runtime, "s1"))

    # Each call re-runs read(); no cache entries persist.
    assert a == {"call": 1}
    assert b == {"call": 2}
    assert c == {"call": 3}
    assert resource.read_count == 3
    assert runtime.resources.get_stats()["cached_entries"] == 0


# ────────────────────────────────────────────────────────────────────
# clear_cache — drops every entry for a URI across all sessions
# ────────────────────────────────────────────────────────────────────


async def test_clear_cache_drops_all_session_keyed_entries(
    runtime: KaosRuntime,
) -> None:
    resource = _CtxAwareResource()
    runtime.resources.register_resource(resource)

    await runtime.resources.get_resource("kaos://test/per-session", context=_ctx(runtime, "s1"))
    await runtime.resources.get_resource("kaos://test/per-session", context=_ctx(runtime, "s2"))
    assert runtime.resources.get_stats()["cached_entries"] == 2

    runtime.resources.clear_cache("kaos://test/per-session")
    assert runtime.resources.get_stats()["cached_entries"] == 0
