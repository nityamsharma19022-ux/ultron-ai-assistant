"""Talks to ULTRON Core as this PC's device."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from ultron_agent import __version__, credentials


class AuthError(Exception):
    pass


class CoreClient:
    def __init__(
        self,
        base_url: str,
        data_dir: Path,
        *,
        transport: httpx.BaseTransport | None = None,
        verify: bool | str = True,
    ) -> None:
        self.data_dir = data_dir
        self.http = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(10.0, read=40.0),
            transport=transport,
            verify=verify,
            headers={"User-Agent": f"ultron-agent/{__version__}"},
        )
        self._access: str | None = None

    def close(self) -> None:
        self.http.close()

    # --- login ----------------------------------------------------------------

    def login(self, email: str, password: str, device_name: str) -> None:
        creds = credentials.load(self.data_dir)
        body: dict[str, Any] = {
            "email": email,
            "password": password,
            "device_name": device_name,
            "platform": "windows",
        }
        if creds:
            body["device_id"] = creds.device_id
        resp = self.http.post("/api/v1/auth/login", json=body)
        if resp.status_code != 200:
            raise AuthError(_detail(resp))
        self._store(resp.json())

    def _store(self, tokens: dict[str, Any]) -> None:
        self._access = tokens["access_token"]
        credentials.save(
            self.data_dir,
            credentials.Credentials(
                device_id=tokens["device_id"], refresh_token=tokens["refresh_token"]
            ),
        )

    def pair(self, code: str, device_name: str) -> None:
        """Signs in with a one-time pairing code (no password)."""
        resp = self.http.post(
            "/api/v1/pairing/redeem",
            json={"code": code, "device_name": device_name, "platform": "windows"},
        )
        if resp.status_code != 200:
            raise AuthError(_detail(resp))
        self._store(resp.json())

    def refresh(self) -> None:
        creds = credentials.load(self.data_dir)
        if creds is None:
            raise AuthError("Not signed in. Run: ultron-agent login")
        resp = self.http.post("/api/v1/auth/refresh", json={"refresh_token": creds.refresh_token})
        if resp.status_code != 200:
            raise AuthError(
                "Sign-in expired or this device was signed out. Run: ultron-agent login"
            )
        self._store(resp.json())

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._access is None:
            self.refresh()
        resp = self.http.request(method, url, headers=self._headers(), **kwargs)
        if resp.status_code == 401:
            self.refresh()
            resp = self.http.request(method, url, headers=self._headers(), **kwargs)
        return resp

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access}"}

    # --- agent protocol ---------------------------------------------------------

    def hello(self, tools: list[str], capabilities: dict[str, list[str]]) -> dict[str, Any]:
        resp = self.request(
            "POST",
            "/api/v1/agents/hello",
            json={"tools": tools, "capabilities": capabilities, "version": __version__},
        )
        resp.raise_for_status()
        return resp.json()

    def next_step(self, wait: int) -> dict[str, Any] | None:
        resp = self.request("GET", "/api/v1/agents/steps/next", params={"wait": wait})
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        return resp.json()

    def progress(self, step_id: str, message: str) -> bool:
        """Returns True when the user cancelled the task."""
        resp = self.request(
            "POST", f"/api/v1/agents/steps/{step_id}/progress", json={"message": message[:300]}
        )
        return resp.status_code == 200 and bool(resp.json().get("cancel"))

    def result(
        self,
        step_id: str,
        *,
        ok: bool,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        retryable: bool = False,
    ) -> None:
        resp = self.request(
            "POST",
            f"/api/v1/agents/steps/{step_id}/result",
            json={"ok": ok, "result": result or {}, "error": error, "retryable": retryable},
        )
        resp.raise_for_status()


def _detail(resp: httpx.Response) -> str:
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None
    return str(detail or f"HTTP {resp.status_code}")
