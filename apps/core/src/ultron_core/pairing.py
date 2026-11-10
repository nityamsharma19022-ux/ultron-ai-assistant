"""Pairing new devices with a one-time code (/api/v1/pairing).

A signed-in device (for example the Control Center on your PC) creates a
code. The new device (your phone, or the Windows agent) enters it within 10
minutes and gets its own sign-in, without typing your password. Codes are
single-use, stored only as a hash in Redis, and redemption is rate-limited.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from ultron_core import __version__, activity, ratelimit, tls
from ultron_core.auth import service as auth_service
from ultron_core.auth.schemas import TokenPair
from ultron_core.db.models import Device, User
from ultron_core.deps import PrincipalDep, RedisDep, SessionDep, SettingsDep
from ultron_core.redis_client import redis_key

router = APIRouter(prefix="/pairing", tags=["pairing"])

CODE_TTL = timedelta(minutes=10)
# No 0/O, 1/I/L: easy to read out and type on a phone.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class CodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["android", "windows", "other"] | None = None


class CodeOut(BaseModel):
    code: str
    expires_at: datetime
    tls: bool
    fingerprint: str | None
    short_fingerprint: str | None


class RedeemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=6, max_length=20)
    device_name: str = Field(min_length=1, max_length=120)
    platform: Literal["android", "windows", "other"]


class InfoOut(BaseModel):
    service: str
    version: str
    tls: bool
    fingerprint: str | None
    short_fingerprint: str | None


def normalize(code: str) -> str:
    return "".join(c for c in code.upper() if c.isalnum())


def _key(settings, code: str) -> str:  # type: ignore[no-untyped-def]
    digest = hashlib.sha256(normalize(code).encode()).hexdigest()
    return redis_key(settings, "pairing", digest)


def _tls_info(settings) -> tuple[str | None, str | None]:  # type: ignore[no-untyped-def]
    if not settings.tls_cert_file:
        return None, None
    fp = tls.fingerprint(Path(settings.tls_cert_file))
    return fp, tls.short(fp)


@router.get("/info", response_model=InfoOut)
async def info(settings: SettingsDep) -> InfoOut:
    """Public: what a new device checks before pairing."""
    fp, short = _tls_info(settings)
    return InfoOut(
        service="ultron-core",
        version=__version__,
        tls=fp is not None,
        fingerprint=fp,
        short_fingerprint=short,
    )


@router.post("/codes", response_model=CodeOut, status_code=status.HTTP_201_CREATED)
async def create_code(
    body: CodeIn,
    principal: PrincipalDep,
    settings: SettingsDep,
    redis: RedisDep,
    session: SessionDep,
) -> CodeOut:
    code = "".join(secrets.choice(ALPHABET) for _ in range(8))
    payload = {
        "user_id": str(principal.user.id),
        "by": str(principal.device.id),
        "platform": body.platform,
    }
    await redis.set(_key(settings, code), json.dumps(payload), ex=int(CODE_TTL.total_seconds()))
    activity.record(
        session,
        principal.user.id,
        "pairing.code_created",
        "Created a pairing code",
        device_id=principal.device.id,
    )
    await session.commit()
    fp, short = _tls_info(settings)
    return CodeOut(
        code=f"{code[:4]}-{code[4:]}",
        expires_at=datetime.now(UTC) + CODE_TTL,
        tls=fp is not None,
        fingerprint=fp,
        short_fingerprint=short,
    )


@router.post("/redeem", response_model=TokenPair)
async def redeem(
    body: RedeemIn,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    redis: RedisDep,
) -> TokenPair:
    ip = request.client.host if request.client else "unknown"
    if not await ratelimit.allow(
        redis, settings, bucket="pairing", identity=ip, limit=10, window=600
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts. Wait a few minutes."
        )
    raw = await redis.getdel(_key(settings, body.code))
    if raw is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="That code is wrong or has expired."
        )
    payload = json.loads(raw)
    expected = payload.get("platform")
    if expected and expected != body.platform:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"This code is for pairing a {expected} device."
        )
    user = await session.get(User, uuid.UUID(payload["user_id"]))
    if user is None or not user.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="That code is wrong or has expired."
        )
    device = Device(user_id=user.id, name=body.device_name, platform=body.platform)
    session.add(device)
    await session.flush()
    pair = await auth_service.issue_tokens(session, settings, user, device)
    activity.record(
        session,
        user.id,
        "pairing.device_paired",
        f"Paired a new device: {body.device_name}",
        device_id=device.id,
        detail={"platform": body.platform, "ip": ip},
    )
    await session.commit()
    return pair
