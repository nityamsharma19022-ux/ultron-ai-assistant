"""Password hashing (Argon2 via pwdlib) and token primitives (PyJWT)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from ultron_core.config import Settings

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"  # noqa: S105 (a token *type*, not a secret)

_password_hash = PasswordHash.recommended()  # Argon2id
# Used when the email is unknown so response time doesn't reveal which
# accounts exist.
_DUMMY_HASH = _password_hash.hash("ultron-timing-equaliser")


class TokenError(Exception):
    """Raised for any invalid, expired or malformed access token."""


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    device_id: uuid.UUID
    expires_at: datetime


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Return (valid, new_hash). ``new_hash`` is set when parameters were upgraded."""
    return _password_hash.verify_and_update(password, password_hash)


def burn_dummy_verification(password: str) -> None:
    _password_hash.verify(password, _DUMMY_HASH)


def create_access_token(
    settings: Settings, user_id: uuid.UUID, device_id: uuid.UUID, now: datetime | None = None
) -> tuple[str, datetime]:
    now = now or datetime.now(UTC)
    expires_at = now + timedelta(seconds=settings.access_token_ttl_seconds)
    payload = {
        "sub": str(user_id),
        "did": str(device_id),
        "typ": ACCESS_TOKEN_TYPE,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "nbf": now,
        "exp": expires_at,
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(settings: Settings, token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            leeway=10,
            options={"require": ["exp", "iat", "nbf", "sub", "iss", "aud"]},
        )
        if payload.get("typ") != ACCESS_TOKEN_TYPE:
            raise TokenError("wrong token type")
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            device_id=uuid.UUID(payload["did"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError) as exc:
        raise TokenError(str(exc)) from exc


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
