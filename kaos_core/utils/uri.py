from __future__ import annotations

from dataclasses import dataclass, field
from string import Formatter
from urllib.parse import parse_qs, urlencode, urlparse


@dataclass(slots=True)
class KaosURI:
    scheme: str
    module: str
    resource_type: str
    resource_id: str
    version: str | None = None
    parameters: dict[str, str] = field(default_factory=dict)

    @classmethod
    def parse(cls, uri: str) -> KaosURI:
        parsed = urlparse(uri)
        path = parsed.path.lstrip("/").split("/")
        if parsed.scheme != "kaos" or len(path) < 2:
            msg = f"Invalid KAOS URI: {uri}"
            raise ValueError(msg)
        params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        return cls(
            scheme=parsed.scheme,
            module=parsed.netloc,
            resource_type=path[0],
            resource_id=path[1],
            version=params.pop("version", None),
            parameters=params,
        )

    def to_string(self) -> str:
        query = dict(self.parameters)
        if self.version is not None:
            query["version"] = self.version
        suffix = f"?{urlencode(query)}" if query else ""
        return f"{self.scheme}://{self.module}/{self.resource_type}/{self.resource_id}{suffix}"

    def validate(self) -> bool:
        return all([self.scheme == "kaos", self.module, self.resource_type, self.resource_id])


class URITemplate:
    def __init__(self, template: str) -> None:
        self.template = template

    def format(self, **kwargs: str) -> str:
        return self.template.format(**kwargs)

    def extract_placeholders(self) -> list[str]:
        return [
            field_name for _, field_name, _, _ in Formatter().parse(self.template) if field_name
        ]

    def matches(self, uri: str) -> dict[str, str] | None:
        parts = self.template.split("/")
        uri_parts = uri.split("/")
        if len(parts) != len(uri_parts):
            return None
        result: dict[str, str] = {}
        for template_part, actual_part in zip(parts, uri_parts, strict=True):
            if template_part.startswith("{") and template_part.endswith("}"):
                result[template_part[1:-1]] = actual_part
            elif template_part != actual_part:
                return None
        return result
