"""Authentication use-cases: login, refresh-token rotation, logout, device revocation."""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ultron_core.auth import security
from ultron_core.auth.schemas import EMAIL_PATTERN, TokenPair
from ultron_core.config import Settings
from ultron_core.db.models import Device, RefreshToken, User
from ultron_core.logging_setup import get_logger

log = get_logger("ultron.auth")

MIN_PASSWORD_LENGTH = 12


class AuthError(Exception):
    """Generic authentication failure (always reported as 401, no details)."""


class OwnerExistsError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Principal:
    user: User
    device: Device


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def create_owner(
    session: AsyncSession, email: str, password: str, display_name: str | None = None
) -> User:
    if len(email) > 320 or not re.match(EMAIL_PATTERN, email.strip()):
        raise ValueError("Enter a valid email address.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    existing = await session.scalar(select(User).where(User.is_owner.is_(True)))
    if existing is not None:
        raise OwnerExistsError("An owner account already exists.")
    password_hash = await asyncio.to_thread(security.hash_password, password)
    user = User(
        email=normalize_email(email),
        display_name=display_name,
        password_hash=password_hash,
        is_active=True,
        is_owner=True,
    )
    session.add(user)
    await session.commit()
    log.info("auth.owner_created", user_id=str(user.id))
    return user


async def _authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        await asyncio.to_thread(security.burn_dummy_verification, password)
        raise AuthError
    valid, new_hash = await asyncio.to_thread(
        security.verify_password, password, user.password_hash
    )
    if not valid or not user.is_active:
        raise AuthError
    if new_hash:
        user.password_hash = new_hash
    return user


async def _issue_tokens(
    session: AsyncSession, settings: Settings, user: User, device: Device, family_id: uuid.UUID
) -> TokenPair:
    now = datetime.now(UTC)
    access_token, _ = security.create_access_token(settings, user.id, device.id, now=now)
    raw_refresh = security.new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            device_id=device.id,
            family_id=family_id,
            token_hash=security.hash_refresh_token(raw_refresh),
            expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    device.last_seen_at = now
    return TokenPair(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.access_token_ttl_seconds,
        device_id=device.id,
    )


async def login(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    password: str,
    device_name: str,
    platform: str,
    device_id: uuid.UUID | None = None,
) -> TokenPair:
    user = await _authenticate(session, email, password)

    device: Device | None = None
    if device_id is not None:
        candidate = await session.get(Device, device_id)
        if candidate is not None and candidate.user_id == user.id and not candidate.is_revoked:
            device = candidate
            device.name = device_name
    if device is None:
        device = Device(user_id=user.id, name=device_name, platform=platform)
        session.add(device)
        await session.flush()

    pair = await _issue_tokens(session, settings, user, device, family_id=uuid.uuid4())
    await session.commit()
    log.info("auth.login", user_id=str(user.id), device_id=str(device.id), platform=platform)
    return pair


async def refresh(session: AsyncSession, settings: Settings, raw_token: str) -> TokenPair:
    token = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == security.hash_refresh_token(raw_token))
        .with_for_update()
    )
    if token is None:
        raise AuthError

    now = datetime.now(UTC)
    if token.used_at is not None or token.revoked_at is not None:
        # A rotated token was presented again: assume it was stolen and kill
        # every token from that login.
        await _revoke_family(session, token.family_id, now)
        await session.commit()
        log.warning("auth.refresh_reuse_detected", device_id=str(token.device_id))
        raise AuthError
    if token.expires_at <= now:
        raise AuthError

    device = await session.get(Device, token.device_id)
    user = await session.get(User, token.user_id)
    if device is None or user is None or device.is_revoked or not user.is_active:
        raise AuthError

    token.used_at = now
    pair = await _issue_tokens(session, settings, user, device, family_id=token.family_id)
    await session.commit()
    return pair


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def revoke_device(session: AsyncSession, user: User, device_id: uuid.UUID) -> bool:
    device = await session.get(Device, device_id)
    if device is None or device.user_id != user.id:
        return False
    now = datetime.now(UTC)
    if device.revoked_at is None:
        device.revoked_at = now
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.device_id == device_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await session.commit()
    log.info("auth.device_revoked", user_id=str(user.id), device_id=str(device_id))
    return True


async def resolve_principal(
    session: AsyncSession, settings: Settings, access_token: str
) -> Principal:
    try:
        claims = security.decode_access_token(settings, access_token)
    except security.TokenError as exc:
        raise AuthError from exc
    user = await session.get(User, claims.user_id)
    device = await session.get(Device, claims.device_id)
    if (
        user is None
        or device is None
        or not user.is_active
        or device.user_id != user.id
        or device.is_revoked
    ):
        raise AuthError
    return Principal(user=user, device=device)


async def list_devices(session: AsyncSession, user: User) -> list[Device]:
    result = await session.scalars(
        select(Device).where(Device.user_id == user.id).order_by(Device.created_at)
    )
    return list(result)
