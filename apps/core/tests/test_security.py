"""Password hashing and token primitives."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from ultron_core.auth import security
from ultron_core.config import Settings

LOCAL = "postgresql://u:p@localhost:5433/ultron"


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, local_database_url=LOCAL, jwt_secret="k" * 48)  # type: ignore[call-arg]


def test_password_hash_roundtrip() -> None:
    hashed = security.hash_password("a-long-password-123")
    assert hashed.startswith("$argon2id$")
    assert security.verify_password("a-long-password-123", hashed)[0] is True
    assert security.verify_password("wrong-password", hashed)[0] is False


def test_access_token_roundtrip(settings: Settings) -> None:
    uid, did = uuid.uuid4(), uuid.uuid4()
    token, expires = security.create_access_token(settings, uid, did)
    claims = security.decode_access_token(settings, token)
    assert (claims.user_id, claims.device_id) == (uid, did)
    assert expires > datetime.now(UTC)


def test_expired_token_rejected(settings: Settings) -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    token, _ = security.create_access_token(settings, uuid.uuid4(), uuid.uuid4(), now=past)
    with pytest.raises(security.TokenError):
        security.decode_access_token(settings, token)


def test_token_signed_with_other_secret_rejected(settings: Settings) -> None:
    other = settings.model_copy(update={"jwt_secret": settings.jwt_secret.__class__("o" * 48)})
    token, _ = security.create_access_token(other, uuid.uuid4(), uuid.uuid4())
    with pytest.raises(security.TokenError):
        security.decode_access_token(settings, token)


def test_wrong_audience_rejected(settings: Settings) -> None:
    other = settings.model_copy(update={"jwt_audience": "someone-else"})
    token, _ = security.create_access_token(other, uuid.uuid4(), uuid.uuid4())
    with pytest.raises(security.TokenError):
        security.decode_access_token(settings, token)


def test_non_access_token_type_rejected(settings: Settings) -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "did": str(uuid.uuid4()),
            "typ": "refresh",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(security.TokenError):
        security.decode_access_token(settings, token)


def test_alg_none_rejected(settings: Settings) -> None:
    token = jwt.encode({"sub": "x"}, key=None, algorithm="none")
    with pytest.raises(security.TokenError):
        security.decode_access_token(settings, token)


def test_refresh_tokens_are_random_and_hash_is_stable() -> None:
    a, b = security.new_refresh_token(), security.new_refresh_token()
    assert a != b and len(a) >= 60
    assert security.hash_refresh_token(a) == security.hash_refresh_token(a)
    assert len(security.hash_refresh_token(a)) == 64
