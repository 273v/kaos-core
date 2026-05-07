"""Centralized security knobs for outbound HTTP, URL handling, and response size caps.

All defaults are strict: private networks, loopback, link-local, and known cloud
metadata-service endpoints are blocked; outbound schemes are restricted to
``http`` and ``https``; response bodies are capped at 100 MB.

Override per-call by passing a ``KaosSecuritySettings`` instance to a security
helper, or flip an individual field via the ``KAOS_SECURITY_<FIELD>`` env var.

Example:

    >>> from kaos_core.security import KaosSecuritySettings, validate_outbound_url
    >>> settings = KaosSecuritySettings(allowed_hosts=["10.0.0.0/24"])
    >>> validate_outbound_url("http://10.0.0.5/internal", settings=settings)
    'http://10.0.0.5/internal'
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KaosSecuritySettings(BaseSettings):
    """Strict-by-default security knobs for KAOS outbound HTTP and URL handling.

    Each field is overridable via the ``KAOS_SECURITY_<FIELD>`` environment
    variable (e.g. ``KAOS_SECURITY_BLOCK_PRIVATE_NETWORKS=0``,
    ``KAOS_SECURITY_ALLOWED_HOSTS=internal.example.com,10.0.0.0/24``,
    ``KAOS_SECURITY_RESPONSE_MAX_BYTES=500000000``).

    Helpers in :mod:`kaos_core.security.url` and
    :mod:`kaos_core.security.size_cap` accept per-call overrides that win
    over these settings, for use cases where a single tool legitimately needs
    relaxed (or stricter) policy without affecting global defaults.
    """

    block_private_networks: bool = True
    """Block RFC1918 (10/8, 172.16/12, 192.168/16), unique-local IPv6 (fc00::/7),
    and link-local (169.254.0.0/16, fe80::/10) destinations."""

    block_metadata_services: bool = True
    """Block known cloud instance-metadata-service endpoints (AWS/Azure/GCP IMDS).
    Separate from :attr:`block_private_networks` so the metadata block can stay
    on even when private-network access is allowed."""

    block_loopback: bool = True
    """Block IPv4 loopback (127.0.0.0/8) and IPv6 loopback (::1)."""

    allowed_schemes: tuple[str, ...] = ("http", "https")
    """Schemes accepted for outbound HTTP. The separate XSS-shape blocklist
    (``javascript:``, ``data:``, ``vbscript:``, ``file:``) is enforced
    regardless of this list."""

    allowed_hosts: list[str] = Field(default_factory=list)
    """Allowlist that bypasses the private/loopback/metadata blocks.

    Each entry is one of:
      * an exact hostname  — ``internal.example.com``
      * a hostname suffix  — ``.example.com`` (matches any host ending in it)
      * a CIDR string      — ``10.0.0.0/24``, ``2001:db8::/32``
    """

    response_max_bytes: int = Field(default=100_000_000, ge=1)
    """Hard cap on a single HTTP response body. Enforced both via pre-flight
    ``Content-Length`` check and via streaming budget on ``aiter_bytes``."""

    response_size_check_via_content_length: bool = True
    """Enable the pre-flight ``Content-Length`` header check."""

    response_size_check_via_streaming: bool = True
    """Enable the streaming budget on ``aiter_bytes`` reads. Disable only if
    you accept post-hoc detection on already-loaded responses."""

    model_config = SettingsConfigDict(
        env_prefix="KAOS_SECURITY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
