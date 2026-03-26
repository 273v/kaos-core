from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kaos_core.base.resource import KaosResource
from kaos_core.exceptions import RegistryError
from kaos_core.types.enums import ResourceType
from kaos_core.types.metadata import ResourceMetadata

if TYPE_CHECKING:
    from kaos_core.base.context import KaosContext


class ResourceRegistry:
    def __init__(self) -> None:
        self._resources: dict[str, KaosResource] = {}
        self._templates: dict[str, str] = {}
        self._cache: dict[str, Any] = {}

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

    async def get_resource(
        self,
        uri: str,
        use_cache: bool = True,
        context: KaosContext | None = None,
    ) -> Any:
        if use_cache and uri in self._cache:
            return self._cache[uri]
        try:
            resource = self._resources[uri]
        except KeyError as exc:
            raise RegistryError("Unknown resource", uri=uri) from exc
        value = await resource.read(context=context)
        if use_cache:
            self._cache[uri] = value
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
        if uri is None:
            self._cache.clear()
            return
        self._cache.pop(uri, None)

    def get_stats(self) -> dict[str, int]:
        return {
            "resources": len(self._resources),
            "templates": len(self._templates),
            "cached_entries": len(self._cache),
        }
