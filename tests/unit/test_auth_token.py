"""Tests for the OAuthToken model extensions (F2.4).

The new fields (``issuer``, ``client_id``, ``obtained_at``) and
the ``is_expired_within(seconds)`` helper are forward-declarations
for the refresh helper. Existing serialized tokens that don't
carry the new fields must still load.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import SecretStr

from kaos_core.config import OAuthToken


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class TestOAuthTokenFields:
    def test_minimal_token_has_no_metadata(self) -> None:
        token = OAuthToken(access_token=SecretStr("x"), token_type="Bearer")
        assert token.issuer is None
        assert token.client_id is None
        assert token.obtained_at is None
        assert token.expires_at is None

    def test_full_token_round_trip(self) -> None:
        token = OAuthToken(
            access_token=SecretStr("atk"),
            token_type="Bearer",
            expires_at="2030-01-01T00:00:00+00:00",
            refresh_token=SecretStr("rtk"),
            scope="read write",
            issuer="https://idp.example/oauth/token",
            client_id="abc123",
            obtained_at="2026-05-10T12:00:00+00:00",
        )
        assert token.issuer == "https://idp.example/oauth/token"
        assert token.client_id == "abc123"
        assert token.obtained_at == "2026-05-10T12:00:00+00:00"

    def test_legacy_serialized_token_still_loads(self) -> None:
        # New fields must be Optional with None default so an
        # existing on-disk token from before F2.4 deserializes
        # without errors.
        legacy_payload = {
            "access_token": "x",
            "token_type": "Bearer",
            "expires_at": None,
            "refresh_token": None,
            "scope": None,
        }
        token = OAuthToken.model_validate(legacy_payload)
        assert token.issuer is None
        assert token.client_id is None


class TestIsExpired:
    def test_no_expiry_returns_false(self) -> None:
        token = OAuthToken(access_token=SecretStr("x"), token_type="Bearer")
        assert token.is_expired() is False

    def test_future_expiry_returns_false(self) -> None:
        future = datetime.now(UTC) + timedelta(hours=1)
        token = OAuthToken(
            access_token=SecretStr("x"), token_type="Bearer", expires_at=_iso(future)
        )
        assert token.is_expired() is False

    def test_past_expiry_returns_true(self) -> None:
        past = datetime.now(UTC) - timedelta(seconds=5)
        token = OAuthToken(access_token=SecretStr("x"), token_type="Bearer", expires_at=_iso(past))
        assert token.is_expired() is True

    def test_zulu_format_parses(self) -> None:
        # Some IdPs emit the trailing 'Z' rather than '+00:00';
        # OAuthToken.is_expired() converts both.
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        token = OAuthToken(access_token=SecretStr("x"), token_type="Bearer", expires_at=future)
        assert token.is_expired() is False


class TestIsExpiredWithin:
    def test_no_expiry_returns_false(self) -> None:
        token = OAuthToken(access_token=SecretStr("x"), token_type="Bearer")
        assert token.is_expired_within(60) is False

    def test_returns_true_when_within_window(self) -> None:
        soon = datetime.now(UTC) + timedelta(seconds=20)
        token = OAuthToken(access_token=SecretStr("x"), token_type="Bearer", expires_at=_iso(soon))
        assert token.is_expired_within(30) is True

    def test_returns_false_when_outside_window(self) -> None:
        later = datetime.now(UTC) + timedelta(minutes=5)
        token = OAuthToken(access_token=SecretStr("x"), token_type="Bearer", expires_at=_iso(later))
        assert token.is_expired_within(30) is False

    def test_negative_seconds_raises(self) -> None:
        token = OAuthToken(access_token=SecretStr("x"), token_type="Bearer")
        try:
            token.is_expired_within(-1)
        except ValueError as exc:
            assert "non-negative" in str(exc)
        else:
            raise AssertionError("expected ValueError for negative seconds")
