from __future__ import annotations

from datetime import UTC, datetime

from pydantic import SecretStr

from kaos_core.types.content import KaosModel


class OAuthToken(KaosModel):
    access_token: SecretStr
    token_type: str
    expires_at: str | None = None
    refresh_token: SecretStr | None = None
    scope: str | None = None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        expiry = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return expiry <= datetime.now(UTC)
