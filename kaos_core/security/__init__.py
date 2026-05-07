"""KAOS security primitives — outbound URL validation, response size caps.

Single source of truth for "is this URL safe to fetch?" and "is this response
body too large?" across the KAOS platform. All defaults are strict; everything
is configurable via :class:`KaosSecuritySettings` (env: ``KAOS_SECURITY_*``)
or per-call overrides.

Public surface:

* :class:`KaosSecuritySettings` — the configuration class.
* :class:`UnsafeURLError`, :class:`ResponseSizeError` — exception types
  (re-exported from :mod:`kaos_core.exceptions` for proximity).
* :func:`is_safe_url` — XSS-shape scheme blocklist (``javascript``, ``data``,
  ``vbscript``, ``file``). Used by HTML/Markdown serializers.
* :func:`validate_outbound_url` — full SSRF guard for outbound HTTP fetches.
* :func:`is_private_ip`, :func:`is_loopback`, :func:`is_metadata_service` —
  predicates used by the SSRF guard, exposed for callers that need them.
* :func:`check_content_length`, :func:`cap_loaded_bytes`,
  :func:`read_capped_bytes`, :func:`read_capped_json` — response size guards.

See :mod:`kaos_core.security.url` and :mod:`kaos_core.security.size_cap` for
the per-helper documentation.
"""

from __future__ import annotations

from kaos_core.exceptions import ResponseSizeError, UnsafeURLError
from kaos_core.security.settings import KaosSecuritySettings
from kaos_core.security.size_cap import (
    cap_loaded_bytes,
    check_content_length,
    read_capped_bytes,
    read_capped_json,
)
from kaos_core.security.url import (
    UNSAFE_SCHEMES,
    is_loopback,
    is_metadata_service,
    is_private_ip,
    is_safe_url,
    validate_outbound_url,
)

__all__ = [
    "UNSAFE_SCHEMES",
    "KaosSecuritySettings",
    "ResponseSizeError",
    "UnsafeURLError",
    "cap_loaded_bytes",
    "check_content_length",
    "is_loopback",
    "is_metadata_service",
    "is_private_ip",
    "is_safe_url",
    "read_capped_bytes",
    "read_capped_json",
    "validate_outbound_url",
]
