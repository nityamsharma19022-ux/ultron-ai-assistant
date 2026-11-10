"""The agent's login (device id and refresh token).

On Windows the file is encrypted with DPAPI for the current Windows user,
so it can't be read by other accounts or copied to another PC. Elsewhere it
is a file only the owner can read (0600).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


@dataclass
class Credentials:
    device_id: str
    refresh_token: str


def _protect(data: bytes) -> bytes:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = (("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char)))

    source = Blob(len(data), ctypes.create_string_buffer(data, len(data)))
    out = Blob()
    if not ctypes.windll.crypt32.CryptProtectData(  # type: ignore[attr-defined]
        ctypes.byref(source), "ULTRON agent", None, None, None, 0, ctypes.byref(out)
    ):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)  # type: ignore[attr-defined]


def _unprotect(data: bytes) -> bytes:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = (("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char)))

    source = Blob(len(data), ctypes.create_string_buffer(data, len(data)))
    out = Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(  # type: ignore[attr-defined]
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(out)
    ):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)  # type: ignore[attr-defined]


def path(data_dir: Path) -> Path:
    return data_dir / ("credentials.dpapi" if IS_WINDOWS else "credentials.json")


def save(data_dir: Path, creds: Credentials) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(asdict(creds)).encode()
    target = path(data_dir)
    tmp = target.with_suffix(".tmp")
    if IS_WINDOWS:
        tmp.write_bytes(_protect(raw))
    else:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
    tmp.replace(target)


def load(data_dir: Path) -> Credentials | None:
    target = path(data_dir)
    if not target.exists():
        return None
    raw = target.read_bytes()
    if IS_WINDOWS:
        raw = _unprotect(raw)
    data = json.loads(raw)
    return Credentials(device_id=data["device_id"], refresh_token=data["refresh_token"])


def clear(data_dir: Path) -> None:
    target = path(data_dir)
    if target.exists():
        target.unlink()
