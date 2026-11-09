"""Request/response models for the auth API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Platform = Literal["android", "windows", "other"]


# Deliberately simple: the email is only a login identifier, and personal
# setups may use private domains such as "me@ultron.local".
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+$"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=1, max_length=1024)
    device_name: str = Field(min_length=1, max_length=120)
    platform: Platform
    # Sent by a device that already has an id, so re-login keeps its identity.
    device_id: uuid.UUID | None = None


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int
    device_id: uuid.UUID


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    is_owner: bool


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    platform: str
    created_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None


class MeResponse(BaseModel):
    user: UserOut
    device: DeviceOut
