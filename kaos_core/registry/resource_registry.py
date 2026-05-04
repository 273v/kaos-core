from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kaos_core.base.resource import KaosResource
from kaos_core.exceptions import RegistryError
from kaos_core.types.enums import ResourceType
from kaos_core.types.metadata import ResourceMetadata

if TYPE_CHECKING:
    from kaos_core.base.context import KaosContext


# Cache key: (uri, session_id_or_None). Keying by URI alone is unsafe
# because a context-aware resource (e.g., one that returns
# context.session_id) would leak the first caller's value to every
# subsequent caller. See `KaosResource.cache_scope`.
_CacheKey = tuple[str, str | None]


class ResourceRegistry:
    def __init__(self) -> None:
        self._resources: dict[str, KaosResource] = {}
        self._templates: dict[str, str] = {}
        self._cache: dict[_CacheKey, Any] = {}

    def register_resource(
        self,
        resource: KaosResource,
        uri: str | None = None,
        templates: list[str] | None = None,
    ) -> None:
        target_uri = uri or resource.metadata.uri
        if target_uri in self._resources:
            raise RegistryError("Resource already registered", uri=target_uri)
        self._resources[target_uri] = resource
        for template in templates or []:
            self._templates[template] = target_uri

    def _cache_key(
        self, uri: str, resource: KaosResource, context: KaosContext | None
    ) -> _CacheKey | None:
        """Compute the cache key for ``(uri, resource, context)``.

        Returns ``None`` when the resource opts out of caching
        (``cache_scope = "none"``).
        """
        scope = getattr(resource, "cache_scope", "per-session")
        if scope == "none":
            return None
        if scope == "global":
            # Caller asserts the resource is context-independent.
            return (uri, None)
        # Default: per-session keying. Falls back to (uri, None) when no
        # context is supplied, which is the safe behaviour for an
        # in-process call where there is no session boundary.
        session_id = context.session_id if context is not None else None
        return (uri, session_id)

    async def get_resource(
        self,
        uri: str,
        use_cache: bool = True,
        context: KaosContext | None = None,
    ) -> Any:
        try:
            resource = self._resources[uri]
        except KeyError as exc:
            raise RegistryError("Unknown resource", uri=uri) from exc

        cache_key = self._cache_key(uri, resource, context) if use_cache else None
        if cache_key is not None and cache_key in self._cache:
            return self._cache[cache_key]

        value = await resource.read(context=context)
        if cache_key is not None:
            self._cache[cache_key] = value
        return value

    def search_resources(
        self,
        *,
        resource_type: ResourceType | None = None,
        module: str | None = None,
        tags: list[str] | None = None,
        query: str | None = None,
    ) -> list[ResourceMetadata]:
        results: list[ResourceMetadata] = []
        for resource in self._resources.values():
            metadata = resource.metadata
            if resource_type and metadata.resource_type != resource_type:
                continue
            if module and metadata.provider_module != module:
                continue
            if tags and not set(tags).issubset(metadata.tags):
                continue
            if query and query.lower() not in f"{metadata.name} {metadata.description}".lower():
                continue
            results.append(metadata)
        return results

    def list_templates(self) -> list[str]:
        return sorted(self._templates)

    def resolve_template(self, template: str, **kwargs: str) -> str:
        if template in self._templates:
            template = self._templates[template]
        return template.format(**kwargs)

    def clear_cache(self, uri: str | None = None) -> None:
        """Clear cache entries.

        If ``uri`` is ``None``, every entry is dropped. Otherwise every
        entry matching that URI (across all sessions) is dropped.
        """
        if uri is None:
            self._cache.clear()
            return
        for key in list(self._cache):
            if key[0] == uri:
                del self._cache[key]

    def get_stats(self) -> dict[str, int]:
        return {
            "resources": len(self._resources),
            "templates": len(self._templates),
            "cached_entries": len(self._cache),
        }
