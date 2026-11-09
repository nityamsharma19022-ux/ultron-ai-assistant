"""CLI: check-config shows the active setup without leaking secrets."""

from __future__ import annotations

import pytest

from ultron_core import cli
from ultron_core.config import get_settings


def test_check_config_hides_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ULTRON_DB_MODE", "local")
    monkeypatch.setenv("ULTRON_LOCAL_DATABASE_URL", "postgresql://u:topsecretpw@dbhost:5433/ultron")
    monkeypatch.setenv("ULTRON_JWT_SECRET", "j" * 40)
    get_settings.cache_clear()
    try:
        assert cli.main(["check-config"]) == 0
    finally:
        get_settings.cache_clear()
    out = capsys.readouterr().out
    assert "dbhost:5433/ultron" in out
    assert "topsecretpw" not in out
    assert "j" * 40 not in out
