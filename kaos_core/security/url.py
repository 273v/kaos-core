"""URL safety primitives — scheme validation, SSRF guards, host allowlists.

This module is the single source of truth for "is this URL safe to fetch?" across
the KAOS platform. It supersedes the package-private ``kaos_content._security``
module (which now re-exports :func:`is_safe_url` from here for back-compat).

Two layers of defence:

1. :func:`is_safe_url` — XSS-shaped scheme rejection (``javascript``, ``data``,
   ``vbscript``, ``file``). Used by HTML/Markdown serializers when emitting
   user-supplied URLs into rendered output.

2. :func:`validate_outbound_url` — full SSRF guard for outbound HTTP fetches.
   Layered on top of (1), adds: scheme allowlist, private-network /
   loopback / metadata-service blocking, host allowlist, malformed-URL
   rejection. Used by every HTTP connector and API client that takes
   user-supplied or third-party URLs.

All checks are stdlib-only (``ipaddress``, ``urllib.parse``, ``html``). No DNS
resolution: callers pass either an IP literal or a hostname; hostname-only
inputs are checked against the static allowlist and the scheme/format gates,
not against private-network ranges (a hostname can resolve to anything; this
function intentionally does not protect against DNS rebinding — that requires
a connect-time hook on the HTTP client).
"""

from __future__ import annotations

import html as _stdlib_html
import ipaddress
from collections.abc import Iterable
from urllib.parse import unquote, urlparse

from kaos_core.exceptions import UnsafeURLError
from kaos_core.security.settings import KaosSecuritySettings

UNSAFE_SCHEMES: frozenset[str] = frozenset({"javascript", "data", "vbscript", "file"})
"""URI schemes rejected by :func:`is_safe_url`.

- ``javascript`` / ``vbscript``: execute as scripts when navigated.
- ``data``: can carry inline ``text/html`` payloads with scripts.
- ``file``: can disclose local filesystem paths in HTML/PDF/email contexts.
"""

# Cloud instance-metadata service endpoints. These are the static
# well-known IPs; cloud providers do not put IMDS behind hostnames.
#   AWS / Azure / GCP IPv4: 169.254.169.254
#   AWS ECS task metadata:  169.254.170.2
#   GCP IMDS IPv6 (newer):  fd00:ec2::254
_METADATA_HOSTS: frozenset[str] = frozenset(
    {
        "169.254.169.254",
        "169.254.170.2",
        "fd00:ec2::254",
    }
)


def _canonicalize(url: str) -> str:
    """HTML-entity decode + URL percent-decode + strip whitespace/NUL + lowercase.

    Mirrors the canonicalization in :func:`is_safe_url`. Used to defeat the
    bypass classes documented in that function.
    """
    decoded = _stdlib_html.unescape(url)
    decoded = unquote(decoded)
    return "".join(c for c in decoded if not c.isspace() and c != "\x00").lower()


def is_safe_url(url: str) -> bool:
    """Return ``False`` for URLs whose canonical scheme is XSS-dangerous.

    Algorithm: HTML-entity decode → URL percent-decode → strip whitespace /
    NUL bytes → lowercase → check the urlparse scheme against
    :data:`UNSAFE_SCHEMES`, with a defence-in-depth ``startswith`` pass on
    the canonical form.

    Bypass classes the canonicalization defeats:

    * ``"jav\\nascript:alert(1)"``  — newline inside the scheme
    * ``"jav\\tascript:alert(1)"``  — tab inside the scheme
    * ``"&#x6A;avascript:alert(1)"`` — HTML hex entity
    * ``"&#106;avascript:alert(1)"`` — HTML decimal entity
    * ``"javascript%3Aalert(1)"``    — percent-encoded colon
    * ``"javascript:\\x00alert(1)"`` — embedded NUL

    Returns ``True`` for safe URLs (including the empty string and relative
    paths) and ``False`` for any URL whose canonical form is in
    :data:`UNSAFE_SCHEMES`. Malformed inputs return ``False`` (defence-in-
    depth: never propagate exceptions out of this predicate, since it is
    called from inside HTML/Markdown serializers under fuzz testing).

    This is the canonical implementation. ``kaos_content._security.is_safe_url``
    re-exports this function as of ``kaos-content 0.1.0a2``.
    """
    if not url:
        return True
    canonical = _canonicalize(url)
    if not canonical:
        return True
    try:
        parsed = urlparse(canonical)
    except (ValueError, TypeError):
        return False
    if parsed.scheme in UNSAFE_SCHEMES:
        return False
    return all(not canonical.startswith(f"{scheme}:") for scheme in UNSAFE_SCHEMES)


def is_private_ip(host: str) -> bool:
    """Return ``True`` for IPv4/IPv6 hosts in private (RFC1918), ULA, or link-local ranges.

    Returns ``False`` for hostnames that don't parse as an IP literal — this
    function is *not* a DNS resolver. Hostname-based blocking happens at
    connect time (an HTTP client hook), not here.
    """
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_link_local


def is_loopback(host: str) -> bool:
    """Return ``True`` for IPv4/IPv6 loopback (127.0.0.0/8, ::1)."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback


def is_metadata_service(host: str) -> bool:
    """Return ``True`` for known cloud instance-metadata service endpoints.

    Covers AWS/Azure/GCP IMDS (169.254.169.254), AWS ECS task metadata
    (169.254.170.2), and GCP IPv6 IMDS (fd00:ec2::254). The list is
    intentionally conservative: only exact matches against well-known
    endpoints, not the broader link-local range.
    """
    if host in _METADATA_HOSTS:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return str(addr) in _METADATA_HOSTS


def _host_matches_allow_entry(host: str, entry: str) -> bool:
    """Match ``host`` against an :attr:`KaosSecuritySettings.allowed_hosts` entry.

    Three entry shapes:
      * exact hostname or IP literal — ``internal.example.com`` / ``10.0.0.5``
      * suffix hostname              — ``.example.com`` (matches any subdomain)
      * CIDR network                 — ``10.0.0.0/24`` / ``2001:db8::/32``

    Entries that don't parse as a CIDR fall back to hostname comparison.
    """
    entry = entry.strip()
    if not entry:
        return False
    if entry == host:
        return True
    if entry.startswith(".") and host.endswith(entry):
        return True
    # CIDR last — only matches when host parses as an IP.
    try:
        net = ipaddress.ip_network(entry, strict=False)
    except ValueError:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr in net


def validate_outbound_url(
    url: str,
    *,
    settings: KaosSecuritySettings | None = None,
    allow_private: bool | None = None,
    allow_loopback: bool | None = None,
    allow_metadata: bool | None = None,
    allowed_schemes: Iterable[str] | None = None,
    allowed_hosts: Iterable[str] | None = None,
) -> str:
    """Validate that ``url`` is safe to fetch over the network.

    Returns the (unchanged) URL on success. Raises :class:`UnsafeURLError`
    on any of: unsafe scheme, malformed URL, scheme not in the allowlist,
    metadata-service host, loopback host, or private-network host.

    Configuration precedence: per-call kwargs override the corresponding
    :class:`KaosSecuritySettings` fields. ``None`` means "use the settings
    default". ``allowed_hosts`` is a *union* of ``settings.allowed_hosts``
    and the kwarg list — a hit in either bypasses the IP-range blocks.

    Per-call overrides exist for tools that legitimately need relaxed
    policy on a specific call (e.g. fetching from an internal service).
    Prefer the env-var route (``KAOS_SECURITY_*``) for policy-wide
    decisions, the settings instance for per-module policy, and per-call
    kwargs only for narrow exceptions.

    Example::

        # Strict, default — blocks 169.254.169.254 + private nets + loopback
        validate_outbound_url("http://example.com/api")

        # Relax on this call only
        validate_outbound_url(internal_url, allow_private=True)

        # Relax via env, persistent
        # $ export KAOS_SECURITY_ALLOWED_HOSTS=10.0.0.0/24

    Args:
        url: URL to validate.
        settings: Override the env-derived defaults.
        allow_private: Override :attr:`KaosSecuritySettings.block_private_networks`.
        allow_loopback: Override :attr:`KaosSecuritySettings.block_loopback`.
        allow_metadata: Override :attr:`KaosSecuritySettings.block_metadata_services`.
        allowed_schemes: Override :attr:`KaosSecuritySettings.allowed_schemes`.
        allowed_hosts: Additional allowlist entries (union with settings).

    Raises:
        UnsafeURLError: If the URL fails any of the configured checks.
    """
    if settings is None:
        settings = KaosSecuritySettings()

    block_private = settings.block_private_networks if allow_private is None else not allow_private
    block_loop = settings.block_loopback if allow_loopback is None else not allow_loopback
    block_meta = settings.block_metadata_services if allow_metadata is None else not allow_metadata
    schemes = (
        tuple(s.lower() for s in allowed_schemes)
        if allowed_schemes is not None
        else tuple(s.lower() for s in settings.allowed_schemes)
    )

    # Layer 1: XSS-shape scheme blocklist (independent of allowlist).
    if not is_safe_url(url):
        raise UnsafeURLError(url, reason="unsafe_scheme")

    # Layer 2: parse + validate.
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError) as exc:
        raise UnsafeURLError(url, reason="malformed") from exc

    if not parsed.scheme:
        raise UnsafeURLError(
            url,
            reason="malformed",
            message=f"URL {url!r} has no scheme; expected one of {schemes}",
        )
    if parsed.scheme.lower() not in schemes:
        raise UnsafeURLError(
            url,
            reason="unsafe_scheme",
            message=f"Scheme {parsed.scheme!r} not in allowed schemes {schemes}",
        )

    host = parsed.hostname or ""
    if not host:
        raise UnsafeURLError(url, reason="malformed", message=f"URL {url!r} has no host")

    # Layer 3: allowlist short-circuit (union of settings and kwargs).
    allow_entries: list[str] = list(settings.allowed_hosts)
    if allowed_hosts:
        allow_entries.extend(allowed_hosts)
    if any(_host_matches_allow_entry(host, e) for e in allow_entries):
        return url

    # Layer 4: SSRF gates. Classify into the most-specific category so that
    # ``allow_loopback=True`` lets ``127.0.0.1`` through even though it is
    # also "private" per :class:`ipaddress`. Categories are mutually
    # exclusive (most-specific wins): metadata > loopback > private_network.
    if is_metadata_service(host):
        if block_meta:
            raise UnsafeURLError(url, reason="metadata_service", host=host)
    elif is_loopback(host):
        if block_loop:
            raise UnsafeURLError(url, reason="loopback", host=host)
    elif is_private_ip(host) and block_private:
        raise UnsafeURLError(url, reason="private_network", host=host)

    return url
