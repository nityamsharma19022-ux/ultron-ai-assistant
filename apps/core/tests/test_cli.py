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


@pytest.mark.integration
def test_export_command(migrated_database, monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    import asyncio
    import json

    from sqlalchemy import text

    from tests.conftest import OWNER_EMAIL, OWNER_PASSWORD
    from ultron_core.auth.service import create_owner
    from ultron_core.db.session import create_engine, create_sessionmaker

    async def setup() -> None:
        engine = create_engine(migrated_database)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("TRUNCATE users CASCADE"))
            async with create_sessionmaker(engine)() as session:
                await create_owner(session, OWNER_EMAIL, OWNER_PASSWORD, "Owner")
        finally:
            await engine.dispose()

    asyncio.run(setup())
    monkeypatch.setattr(cli, "get_settings", lambda: migrated_database)
    out = tmp_path / "backup" / "ultron.json"
    assert cli.main(["export", "--email", OWNER_EMAIL.upper(), "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["user"]["email"] == OWNER_EMAIL and data["format"] == "ultron-export/1"
    assert OWNER_PASSWORD not in out.read_text(encoding="utf-8")
    assert cli.main(["export", "--email", "nobody@x.test"]) == 1
    assert "No user" in capsys.readouterr().err
