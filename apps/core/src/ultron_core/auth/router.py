"""Auth and device-management endpoints (/api/v1)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status

from ultron_core.auth import service
from ultron_core.auth.rate_limit import LoginRateLimiter
from ultron_core.auth.schemas import (
    DeviceOut,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenPair,
    UserOut,
)
from ultron_core.deps import UNAUTHORIZED, PrincipalDep, RedisDep, SessionDep, SettingsDep

router = APIRouter(tags=["auth"])

_INVALID_LOGIN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid email or password",
    headers={"WWW-Authenticate": "Bearer"},
)


@router.post("/auth/login", response_model=TokenPair)
async def login(
    body: LoginRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    redis: RedisDep,
) -> TokenPair:
    limiter = LoginRateLimiter(redis, settings)
    client_ip = request.client.host if request.client else "unknown"
    if not await limiter.register_attempt(client_ip, body.email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(settings.login_rate_limit_window_seconds)},
        )
    try:
        pair = await service.login(
            session,
            settings,
            email=body.email,
            password=body.password,
            device_name=body.device_name,
            platform=body.platform,
            device_id=body.device_id,
        )
    except service.AuthError:
        raise _INVALID_LOGIN from None
    await limiter.reset_email(body.email)
    return pair


@router.post("/auth/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, session: SessionDep, settings: SettingsDep) -> TokenPair:
    try:
        return await service.refresh(session, settings, body.refresh_token)
    except service.AuthError:
        raise UNAUTHORIZED from None


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(principal: PrincipalDep, session: SessionDep) -> Response:
    await service.revoke_device(session, principal.user, principal.device.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/me", response_model=MeResponse)
async def me(principal: PrincipalDep) -> MeResponse:
    return MeResponse(
        user=UserOut.model_validate(principal.user),
        device=DeviceOut.model_validate(principal.device),
    )


@router.get("/devices", response_model=list[DeviceOut])
async def list_devices(principal: PrincipalDep, session: SessionDep) -> list[DeviceOut]:
    devices = await service.list_devices(session, principal.user)
    return [DeviceOut.model_validate(d) for d in devices]


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    device_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> Response:
    if not await service.revoke_device(session, principal.user, device_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
