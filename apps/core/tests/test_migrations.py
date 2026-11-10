"""Migrations: up/down round trip and models stay in sync with migrations."""

from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import make_test_settings
from ultron_core.db import migrate
from ultron_core.db.base import Base

pytestmark = pytest.mark.integration


async def test_models_match_migrations(migrated_database) -> None:  # type: ignore[no-untyped-def]
    engine = create_async_engine(migrated_database.database_url)

    def diff(sync_conn):  # type: ignore[no-untyped-def]
        ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
        return compare_metadata(ctx, Base.metadata)

    async with engine.connect() as conn:
        changes = await conn.run_sync(diff)
    await engine.dispose()
    assert changes == [], f"Models differ from migrations: {changes}"


def test_downgrade_and_upgrade_round_trip(migrated_database) -> None:  # type: ignore[no-untyped-def]
    migrate.downgrade(migrated_database, "base")
    migrate.upgrade(migrated_database)


def test_head_revision_is_known() -> None:
    assert migrate.head_revision() == "0006"


def test_cloud_migrations_blocked_without_explicit_flag() -> None:
    settings = make_test_settings(
        db_mode="cloud", cloud_database_url="postgresql://u:p@cloud.invalid:5432/postgres"
    )
    with pytest.raises(migrate.CloudMigrationBlockedError):
        migrate.upgrade(settings)
