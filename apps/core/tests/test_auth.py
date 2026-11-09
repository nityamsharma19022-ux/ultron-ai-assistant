"""Authentication flow against the real database and Redis."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import update

from tests.conftest import OWNER_EMAIL, OWNER_PASSWORD, bearer, login
from ultron_core.auth.service import OwnerExistsError, create_owner
from ultron_core.db.models import User

pytestmark = pytest.mark.integration


async def test_login_and_me(client: httpx.AsyncClient, owner: User) -> None:
    resp = await login(client)
    assert resp.status_code == 200, resp.text
    tokens = resp.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 900

    me = await client.get("/api/v1/auth/me", headers=bearer(tokens["access_token"]))
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["email"] == OWNER_EMAIL
    assert body["user"]["is_owner"] is True
    assert body["device"]["id"] == tokens["device_id"]
    assert body["device"]["platform"] == "android"
    assert "password_hash" not in body["user"]


async def test_email_is_case_insensitive(client: httpx.AsyncClient, owner: User) -> None:
    assert (await login(client, email=OWNER_EMAIL.upper())).status_code == 200


async def test_wrong_password_and_unknown_email_look_identical(
    client: httpx.AsyncClient, owner: User
) -> None:
    wrong = await login(client, password="not-the-password")
    unknown = await login(client, email="nobody@ultron.test")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_protected_routes_require_a_valid_token(
    client: httpx.AsyncClient, owner: User
) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    garbage = await client.get("/api/v1/auth/me", headers=bearer("not.a.jwt"))
    assert garbage.status_code == 401
    assert garbage.headers["www-authenticate"] == "Bearer"


async def test_refresh_rotates_tokens(client: httpx.AsyncClient, owner: User) -> None:
    first = (await login(client)).json()
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert resp.status_code == 200
    second = resp.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert second["device_id"] == first["device_id"]
    me = await client.get("/api/v1/auth/me", headers=bearer(second["access_token"]))
    assert me.status_code == 200


async def test_refresh_token_reuse_revokes_the_whole_family(
    client: httpx.AsyncClient, owner: User
) -> None:
    first = (await login(client)).json()
    second = (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    ).json()

    # Replaying the already-used token is treated as theft...
    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert replay.status_code == 401
    # ...so the legitimate newer token is revoked as well.
    after = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert after.status_code == 401


async def test_unknown_refresh_token_rejected(client: httpx.AsyncClient, owner: User) -> None:
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "x" * 64})
    assert resp.status_code == 401


async def test_logout_revokes_device(client: httpx.AsyncClient, owner: User) -> None:
    tokens = (await login(client)).json()
    out = await client.post("/api/v1/auth/logout", headers=bearer(tokens["access_token"]))
    assert out.status_code == 204
    # Access token is rejected immediately (device check), refresh is dead too.
    me = await client.get("/api/v1/auth/me", headers=bearer(tokens["access_token"]))
    assert me.status_code == 401
    ref = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert ref.status_code == 401


async def test_devices_list_and_revoke_other_device(client: httpx.AsyncClient, owner: User) -> None:
    phone = (await login(client, device_name="Pixel", platform="android")).json()
    pc = (await login(client, device_name="Desktop", platform="windows")).json()

    listing = await client.get("/api/v1/devices", headers=bearer(pc["access_token"]))
    assert listing.status_code == 200
    assert {d["platform"] for d in listing.json()} == {"android", "windows"}

    revoke = await client.delete(
        f"/api/v1/devices/{phone['device_id']}", headers=bearer(pc["access_token"])
    )
    assert revoke.status_code == 204
    phone_me = await client.get("/api/v1/auth/me", headers=bearer(phone["access_token"]))
    assert phone_me.status_code == 401
    pc_me = await client.get("/api/v1/auth/me", headers=bearer(pc["access_token"]))
    assert pc_me.status_code == 200

    missing = await client.delete(
        "/api/v1/devices/00000000-0000-0000-0000-000000000000",
        headers=bearer(pc["access_token"]),
    )
    assert missing.status_code == 404


async def test_relogin_with_device_id_keeps_device_identity(
    client: httpx.AsyncClient, owner: User
) -> None:
    first = (await login(client)).json()
    again = (await login(client, device_id=first["device_id"], device_name="Pixel 9")).json()
    assert again["device_id"] == first["device_id"]


async def test_login_rate_limit(client: httpx.AsyncClient, owner: User) -> None:
    # Test settings allow 5 attempts per window.
    for _ in range(5):
        assert (await login(client, password="wrong-password")).status_code == 401
    blocked = await login(client)
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers


async def test_inactive_user_cannot_login(app, client: httpx.AsyncClient, owner: User) -> None:  # type: ignore[no-untyped-def]
    async with app.state.sessionmaker() as session:
        await session.execute(update(User).values(is_active=False))
        await session.commit()
    assert (await login(client)).status_code == 401


async def test_only_one_owner_and_password_policy(app) -> None:  # type: ignore[no-untyped-def]
    async with app.state.sessionmaker() as session:
        with pytest.raises(ValueError, match="12 characters"):
            await create_owner(session, "a@ultron.test", "short")
        await create_owner(session, "a@ultron.test", OWNER_PASSWORD)
        with pytest.raises(OwnerExistsError):
            await create_owner(session, "b@ultron.test", OWNER_PASSWORD)


async def test_password_is_stored_hashed(app, owner: User) -> None:  # type: ignore[no-untyped-def]
    assert owner.password_hash.startswith("$argon2id$")
    assert OWNER_PASSWORD not in owner.password_hash


async def test_owner_with_private_domain_can_log_in(app, client: httpx.AsyncClient) -> None:  # type: ignore[no-untyped-def]
    async with app.state.sessionmaker() as session:
        await create_owner(session, "me@ultron.local", OWNER_PASSWORD)
    assert (await login(client, email="me@ultron.local")).status_code == 200


async def test_owner_email_must_look_like_an_email(app) -> None:  # type: ignore[no-untyped-def]
    async with app.state.sessionmaker() as session:
        with pytest.raises(ValueError, match="valid email"):
            await create_owner(session, "not-an-email", OWNER_PASSWORD)
