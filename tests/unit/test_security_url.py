"""Unit tests for kaos_core.security.url — SSRF guard + scheme validation."""

from __future__ import annotations

import pytest

from kaos_core.exceptions import UnsafeURLError
from kaos_core.security import (
    UNSAFE_SCHEMES,
    KaosSecuritySettings,
    is_loopback,
    is_metadata_service,
    is_private_ip,
    is_safe_url,
    validate_outbound_url,
)

# ---------------------------------------------------------------------------
# is_safe_url — XSS-shape scheme blocklist
# ---------------------------------------------------------------------------


class TestIsSafeUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "",
            "/relative/path",
            "https://example.com",
            "http://example.com/x?q=1",
            "https://user:pass@example.com:8080/path#frag",
            "mailto:a@b.com",  # not in blocklist
            "ftp://example.com/file",  # not in blocklist
        ],
    )
    def test_safe_urls(self, url: str) -> None:
        assert is_safe_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "JAVASCRIPT:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
        ],
    )
    def test_simple_unsafe_urls(self, url: str) -> None:
        assert is_safe_url(url) is False

    @pytest.mark.parametrize(
        "url",
        [
            "jav\nascript:alert(1)",
            "jav\tascript:alert(1)",
            "&#x6A;avascript:alert(1)",
            "&#106;avascript:alert(1)",
            "javascript%3Aalert(1)",
            "javascript\x00:alert(1)",
            "  JAVASCRIPT  :alert(1)",
        ],
    )
    def test_bypass_attempts_blocked(self, url: str) -> None:
        assert is_safe_url(url) is False

    def test_malformed_url_blocked(self) -> None:
        # Bare IPv6 bracket without close — urlparse raises ValueError on 3.6+
        assert is_safe_url("http://[") is False

    def test_unsafe_schemes_constant(self) -> None:
        # If someone changes the constant we want a test failure forcing a review.
        assert frozenset({"javascript", "data", "vbscript", "file"}) == UNSAFE_SCHEMES


# ---------------------------------------------------------------------------
# is_private_ip / is_loopback / is_metadata_service
# ---------------------------------------------------------------------------


class TestNetworkPredicates:
    @pytest.mark.parametrize(
        "host,expected",
        [
            ("10.0.0.1", True),
            ("172.16.5.5", True),
            ("172.31.255.255", True),
            ("172.32.0.1", False),  # outside RFC1918
            ("192.168.1.1", True),
            ("169.254.1.1", True),  # link-local
            ("169.254.169.254", True),  # link-local (also metadata)
            ("8.8.8.8", False),
            ("fc00::1", True),  # ULA
            ("fe80::1", True),  # link-local IPv6
            # 2001:db8::/32 is the IPv6 documentation prefix; ipaddress treats
            # it as private (RFC 6890). Production code should not reach it.
            ("2001:db8::1", True),
            ("example.com", False),  # not an IP literal
            ("not-an-ip", False),
        ],
    )
    def test_is_private_ip(self, host: str, expected: bool) -> None:
        assert is_private_ip(host) is expected

    @pytest.mark.parametrize(
        "host,expected",
        [
            ("127.0.0.1", True),
            ("127.255.255.254", True),
            ("128.0.0.1", False),
            ("::1", True),
            ("8.8.8.8", False),
            ("example.com", False),
        ],
    )
    def test_is_loopback(self, host: str, expected: bool) -> None:
        assert is_loopback(host) is expected

    @pytest.mark.parametrize(
        "host,expected",
        [
            ("169.254.169.254", True),  # AWS/Azure/GCP IMDS
            ("169.254.170.2", True),  # AWS ECS task metadata
            ("fd00:ec2::254", True),  # GCP IPv6 IMDS
            ("169.254.169.253", False),  # close but not exact
            ("169.254.0.1", False),
            ("8.8.8.8", False),
            ("example.com", False),
        ],
    )
    def test_is_metadata_service(self, host: str, expected: bool) -> None:
        assert is_metadata_service(host) is expected


# ---------------------------------------------------------------------------
# validate_outbound_url — full SSRF guard
# ---------------------------------------------------------------------------


class TestValidateOutboundUrl:
    def test_public_https_passes(self) -> None:
        assert validate_outbound_url("https://example.com/api") == "https://example.com/api"

    def test_public_http_passes(self) -> None:
        assert validate_outbound_url("http://example.com/") == "http://example.com/"

    def test_unsafe_scheme_rejected(self) -> None:
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url("javascript:alert(1)")
        assert excinfo.value.reason == "unsafe_scheme"

    def test_data_scheme_rejected(self) -> None:
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url("data:text/html,<script>alert(1)</script>")
        assert excinfo.value.reason == "unsafe_scheme"

    def test_file_scheme_rejected(self) -> None:
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url("file:///etc/passwd")
        assert excinfo.value.reason == "unsafe_scheme"

    def test_disallowed_scheme_rejected(self) -> None:
        # Default allowed_schemes is ('http', 'https'). FTP not in blocklist
        # but not in allowlist either — should be rejected at scheme gate.
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url("ftp://example.com/file")
        assert excinfo.value.reason == "unsafe_scheme"

    def test_no_host_rejected(self) -> None:
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url("https://")
        assert excinfo.value.reason == "malformed"

    def test_no_scheme_rejected(self) -> None:
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url("example.com/path")
        # urlparse treats this as a path-only URL (scheme=''); rejected.
        assert excinfo.value.reason == "malformed"

    def test_metadata_service_blocked(self) -> None:
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url("http://169.254.169.254/latest/meta-data/")
        assert excinfo.value.reason == "metadata_service"
        assert excinfo.value.host == "169.254.169.254"

    def test_loopback_blocked(self) -> None:
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url("http://127.0.0.1:8080/")
        assert excinfo.value.reason == "loopback"

    def test_loopback_ipv6_blocked(self) -> None:
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url("http://[::1]:8080/")
        assert excinfo.value.reason == "loopback"

    def test_private_ipv4_blocked(self) -> None:
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url("http://10.0.0.5/")
        assert excinfo.value.reason == "private_network"
        assert excinfo.value.host == "10.0.0.5"

    def test_private_ipv6_blocked(self) -> None:
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url("http://[fc00::1]/")
        assert excinfo.value.reason == "private_network"

    # ---- per-call overrides ----

    def test_allow_private_per_call(self) -> None:
        url = "http://10.0.0.5/internal"
        assert validate_outbound_url(url, allow_private=True) == url

    def test_allow_loopback_per_call(self) -> None:
        url = "http://127.0.0.1:8080/"
        assert validate_outbound_url(url, allow_loopback=True) == url

    def test_allow_metadata_per_call(self) -> None:
        url = "http://169.254.169.254/latest/meta-data/"
        assert validate_outbound_url(url, allow_metadata=True) == url

    def test_metadata_block_independent_of_private(self) -> None:
        # Even with private allowed, metadata service stays blocked by default.
        url = "http://169.254.169.254/"
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url(url, allow_private=True, allow_loopback=True)
        assert excinfo.value.reason == "metadata_service"

    def test_allowed_schemes_override(self) -> None:
        url = "ftp://example.com/file"
        assert validate_outbound_url(url, allowed_schemes=["http", "https", "ftp"]) == url

    # ---- allowed_hosts allowlist ----

    def test_allowed_host_exact_match(self) -> None:
        url = "http://internal.example.com/api"
        assert validate_outbound_url(url, allowed_hosts=["internal.example.com"]) == url

    def test_allowed_host_suffix_match(self) -> None:
        # ".example.com" matches any subdomain of example.com
        url = "http://api.internal.example.com/v1"
        assert validate_outbound_url(url, allowed_hosts=[".example.com"]) == url

    def test_allowed_host_cidr_v4(self) -> None:
        url = "http://10.0.0.5/internal"
        assert validate_outbound_url(url, allowed_hosts=["10.0.0.0/24"]) == url

    def test_allowed_host_cidr_v6(self) -> None:
        url = "http://[fc00::5]/internal"
        assert validate_outbound_url(url, allowed_hosts=["fc00::/7"]) == url

    def test_allowed_host_outside_cidr_still_blocked(self) -> None:
        url = "http://10.1.0.5/"
        with pytest.raises(UnsafeURLError):
            validate_outbound_url(url, allowed_hosts=["10.0.0.0/24"])

    def test_allowlist_unions_kwargs_and_settings(self) -> None:
        settings = KaosSecuritySettings(allowed_hosts=["a.example.com"])
        url1 = "http://a.example.com/"
        url2 = "http://b.example.com/"
        # settings entry wins
        assert validate_outbound_url(url1, settings=settings) == url1
        # kwarg entry adds to allowlist
        assert (
            validate_outbound_url(url2, settings=settings, allowed_hosts=["b.example.com"]) == url2
        )

    def test_allowlist_does_not_override_unsafe_scheme(self) -> None:
        # Allowlist short-circuits IP-range blocks but not scheme blocks.
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url("javascript:alert(1)", allowed_hosts=["example.com"])
        assert excinfo.value.reason == "unsafe_scheme"

    # ---- settings flag flips ----

    def test_settings_disable_private_block(self) -> None:
        settings = KaosSecuritySettings(block_private_networks=False)
        url = "http://10.0.0.5/"
        assert validate_outbound_url(url, settings=settings) == url

    def test_settings_disable_metadata_block(self) -> None:
        # Most-specific-category semantics: disabling the metadata block is
        # sufficient to let the IMDS host through, even with private/loopback
        # blocks still on. The host is classified as 'metadata_service' and
        # never falls through to the broader checks.
        settings = KaosSecuritySettings(block_metadata_services=False)
        url = "http://169.254.169.254/"
        assert validate_outbound_url(url, settings=settings) == url

    def test_non_metadata_link_local_still_blocked(self) -> None:
        # 169.254.1.1 is link-local but NOT a metadata service. Disabling
        # the metadata block does not let it through; the private-network
        # block still applies (link-local is RFC 6890 private).
        settings = KaosSecuritySettings(block_metadata_services=False)
        url = "http://169.254.1.1/"
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url(url, settings=settings)
        assert excinfo.value.reason == "private_network"

    def test_settings_strict_default(self) -> None:
        # Sanity: a fresh settings instance with no overrides blocks all
        # the things we expect.
        s = KaosSecuritySettings()
        assert s.block_private_networks is True
        assert s.block_loopback is True
        assert s.block_metadata_services is True
        assert s.allowed_schemes == ("http", "https")
        assert s.allowed_hosts == []

    # ---- error envelope ----

    def test_unsafe_url_error_carries_structured_info(self) -> None:
        with pytest.raises(UnsafeURLError) as excinfo:
            validate_outbound_url("http://10.0.0.5/")
        assert excinfo.value.url == "http://10.0.0.5/"
        assert excinfo.value.reason == "private_network"
        assert excinfo.value.host == "10.0.0.5"
        # Ensure __str__ includes the reason
        assert "private_network" in str(excinfo.value)
