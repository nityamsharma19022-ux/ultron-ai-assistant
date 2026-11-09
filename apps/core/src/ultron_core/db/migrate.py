"""Programmatic Alembic helpers (used by the CLI, health checks and tests)."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from ultron_core.config import Settings

SCRIPT_LOCATION = "ultron_core:migrations"


class CloudMigrationBlockedError(RuntimeError):
    pass


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", SCRIPT_LOCATION)
    if database_url:
        # Passed via attributes (not the ini option) so passwords containing
        # "%" don't break configparser interpolation.
        cfg.attributes["database_url"] = database_url
    return cfg


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def ensure_migrations_allowed(settings: Settings) -> None:
    if settings.db_mode == "cloud" and not settings.allow_cloud_migrations:
        raise CloudMigrationBlockedError(
            "Refusing to migrate the CLOUD database. Set "
            "ULTRON_ALLOW_CLOUD_MIGRATIONS=true for this one command if you really mean it."
        )


def upgrade(settings: Settings, revision: str = "head") -> None:
    ensure_migrations_allowed(settings)
    command.upgrade(alembic_config(settings.database_url), revision)


def downgrade(settings: Settings, revision: str) -> None:
    ensure_migrations_allowed(settings)
    command.downgrade(alembic_config(settings.database_url), revision)
