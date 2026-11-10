"""Pairing codes and the HTTPS certificate."""

from __future__ import annotations

import ipaddress

import pytest
from cryptography import x509

from tests.conftest import bearer, make_test_settings, owner_headers, running_app
from tests.fakes import cloud
from ultron_core import tls


def test_certificate_generation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cert, key = tls.generate(tmp_path, ["192.168.1.20", "ultron-pc"])
    parsed = x509.load_pem_x509_certificate(cert.read_bytes())
    san = parsed.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert ipaddress.ip_address("192.168.1.20") in san.get_values_for_type(x509.IPAddress)
    assert "ultron-pc" in san.get_values_for_type(x509.DNSName)
    assert key.stat().st_mode & 0o077 == 0  # private key not readable by others
    fp = tls.fingerprint(cert)
    assert len(fp) == 64 and int(fp, 16) >= 0
    assert (
        tls.short(fp)
        == f"{fp[:4].upper()}-{fp[4:8].upper()} … {fp[-8:-4].upper()}-{fp[-4:].upper()}"
    )


@pytest.mark.integration
async def test_pair_a_phone_with_a_code(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with running_app(migrated_database, [cloud()]) as (app, client):
        pc = await owner_headers(app, client)
        info = (await client.get("/api/v1/pairing/info")).json()
        assert info == {
            "service": "ultron-core",
            "version": info["version"],
            "tls": False,
            "fingerprint": None,
            "short_fingerprint": None,
        }
        assert (await client.post("/api/v1/pairing/codes", json={})).status_code == 401
        made = (
            await client.post("/api/v1/pairing/codes", json={"platform": "android"}, headers=pc)
        ).json()
        code = made["code"]
        assert len(code) == 9 and code[4] == "-"

        wrong = await client.post(
            "/api/v1/pairing/redeem",
            json={"code": code, "device_name": "Laptop", "platform": "windows"},
        )
        assert wrong.status_code == 400 and "android" in wrong.json()["detail"]
        # The wrong-platform attempt used the code up: make another.
        code = (await client.post("/api/v1/pairing/codes", json={}, headers=pc)).json()["code"]
        resp = await client.post(
            "/api/v1/pairing/redeem",
            json={
                "code": code.lower().replace("-", " "),
                "device_name": "iQOO",
                "platform": "android",
            },
        )
        assert resp.status_code == 200, resp.text
        phone = bearer(resp.json()["access_token"])
        me = (await client.get("/api/v1/auth/me", headers=phone)).json()
        assert me["device"]["name"] == "iQOO" and me["device"]["platform"] == "android"
        # Single use.
        again = await client.post(
            "/api/v1/pairing/redeem", json={"code": code, "device_name": "x", "platform": "android"}
        )
        assert again.status_code == 400
        kinds = [e["kind"] for e in (await client.get("/api/v1/activity", headers=pc)).json()]
        assert "pairing.device_paired" in kinds
        # The paired device can be signed out like any other.
        assert (
            await client.delete(f"/api/v1/devices/{me['device']['id']}", headers=pc)
        ).status_code == 204
        assert (await client.get("/api/v1/auth/me", headers=phone)).status_code == 401


@pytest.mark.integration
async def test_code_guessing_is_rate_limited(migrated_database) -> None:  # type: ignore[no-untyped-def]
    async with running_app(migrated_database, [cloud()]) as (app, client):
        await owner_headers(app, client)
        statuses = []
        for _ in range(11):
            resp = await client.post(
                "/api/v1/pairing/redeem",
                json={"code": "AAAA-BBBB", "device_name": "x", "platform": "android"},
            )
            statuses.append(resp.status_code)
        assert statuses[:10] == [400] * 10 and statuses[10] == 429


@pytest.mark.integration
async def test_info_reports_the_certificate(migrated_database, tmp_path) -> None:  # type: ignore[no-untyped-def]
    cert, key = tls.generate(tmp_path, [])
    settings = make_test_settings(
        local_database_url=migrated_database.local_database_url.get_secret_value(),
        tls_cert_file=str(cert),
        tls_key_file=str(key),
    )
    async with running_app(settings, [cloud()]) as (app, client):
        info = (await client.get("/api/v1/pairing/info")).json()
        assert info["tls"] is True and info["fingerprint"] == tls.fingerprint(cert)
        pc = await owner_headers(app, client)
        made = (await client.post("/api/v1/pairing/codes", json={}, headers=pc)).json()
        assert made["short_fingerprint"] == tls.short(tls.fingerprint(cert))
