"""Shared URL and response-size guards for OAuth HTTP calls."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from kaos_core.auth.errors import OAuthFlowError
from kaos_core.exceptions import ResponseSizeError, UnsafeURLError
from kaos_core.security.settings import KaosSecuritySettings
from kaos_core.security.size_cap import cap_loaded_bytes, check_content_length
from kaos_core.security.url import validate_outbound_url

if TYPE_CHECKING:
    import httpx


def validate_oauth_endpoint(
    url: str,
    *,
    label: str,
    settings: KaosSecuritySettings | None = None,
    allowed_schemes: Iterable[str] = ("https",),
) -> str:
    """Validate an OAuth endpoint before an outbound HTTP request."""
    try:
        return validate_outbound_url(
            url,
            settings=settings,
            allowed_schemes=allowed_schemes,
        )
    except UnsafeURLError as exc:
        msg = f"{label} URL is blocked by outbound safety policy: {exc.reason}"
        raise OAuthFlowError(msg) from exc


def response_json(
    response: httpx.Response,
    *,
    label: str,
    settings: KaosSecuritySettings | None = None,
) -> dict[str, Any]:
    """Parse a loaded HTTP response as capped JSON object."""
    resolved = settings or KaosSecuritySettings()
    try:
        if resolved.response_size_check_via_content_length:
            check_content_length(response.headers, settings=resolved)
        cap_loaded_bytes(response.content, settings=resolved)
    except ResponseSizeError as exc:
        msg = f"{label} response exceeds the configured response size cap"
        raise OAuthFlowError(msg) from exc

    try:
        payload = json.loads(response.content)
    except ValueError as exc:
        msg = f"{label} is not JSON (status {response.status_code})"
        raise OAuthFlowError(msg) from exc
    if not isinstance(payload, dict):
        msg = f"{label} returned JSON that is not an object"
        raise OAuthFlowError(msg)
    return payload


__all__ = ["response_json", "validate_oauth_endpoint"]
