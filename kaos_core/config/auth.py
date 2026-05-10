from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import SecretStr

from kaos_core.types.content import KaosModel


class OAuthToken(KaosModel):
    """OAuth 2.0 / 2.1 token bundle.

    Carries the issuer + client_id alongside the bearer credentials
    so a stale token can be refreshed without re-running the full
    authorization flow. The optional ``obtained_at`` timestamp is
    audit / debugging metadata; expiry checking uses
    ``expires_at`` (server-canonical) when present.
    """

    access_token: SecretStr
    token_type: str
    expires_at: str | None = None
    refresh_token: SecretStr | None = None
    scope: str | None = None
    issuer: str | None = None
    """Token endpoint URL — required for refresh."""
    client_id: str | None = None
    """OAuth client identifier — required for refresh."""
    obtained_at: str | None = None
    """ISO-8601 timestamp when the token was acquired (UTC)."""

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return expiry <= datetime.now(UTC)

    def is_expired_within(self, seconds: int) -> bool:
        """Return True if the token expires within *seconds* from now.

        Use this to refresh proactively rather than waiting for a 401.
        Defaults are caller-driven; common practice is 30-60 seconds
        for interactive CLIs and 5 minutes for long-running workers.
        """
        if self.expires_at is None:
            return False
        if seconds < 0:
            msg = "seconds must be non-negative"
            raise ValueError(msg)
        expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return expiry <= datetime.now(UTC) + timedelta(seconds=seconds)
