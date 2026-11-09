"""ULTRON Core command line.

ultron-core check-config        Show the active (non-secret) configuration
ultron-core migrate             Apply database migrations
ultron-core create-owner        Create the single owner account
ultron-core serve               Run the API server
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from ultron_core.config import get_settings


def _local_ai_summary(s) -> str:  # type: ignore[no-untyped-def]
    from ultron_core.ai.local_policy import ollama_address_problem

    if not s.ollama_base_url:
        return "not configured"
    problem = ollama_address_problem(s)
    if problem:
        return f"BLOCKED - {problem}"
    return f"{s.ollama_base_url} model={s.ollama_model}"


def _check_config(_: argparse.Namespace) -> int:
    s = get_settings()
    rows = {
        "env": s.env,
        "deployment": s.deployment,
        "node_id": s.node_id,
        "db_mode": s.db_mode,
        "database_host": s.database_url.split("@")[-1],
        "redis_key_prefix": s.redis_key_prefix,
        "local_ai": _local_ai_summary(s),
        "log_format": s.log_format,
    }
    for key, value in rows.items():
        print(f"{key:18} {value}")
    return 0


def _migrate(args: argparse.Namespace) -> int:
    from ultron_core.db.migrate import upgrade

    s = get_settings()
    upgrade(s, args.revision)
    print(f"Database migrated to {args.revision} ({s.db_mode}).")
    return 0


def _create_owner(args: argparse.Namespace) -> int:
    from ultron_core.auth.service import OwnerExistsError, create_owner
    from ultron_core.db.session import create_engine, create_sessionmaker

    password = os.environ.get("ULTRON_OWNER_PASSWORD")
    if not password:
        password = getpass.getpass("Owner password (min 12 chars): ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match.", file=sys.stderr)
            return 1

    async def run() -> None:
        engine = create_engine(get_settings())
        try:
            async with create_sessionmaker(engine)() as session:
                user = await create_owner(session, args.email, password, args.display_name)
                print(f"Owner created: {user.email} ({user.id})")
        finally:
            await engine.dispose()

    try:
        asyncio.run(run())
    except (OwnerExistsError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "ultron_core.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_config=None,
        proxy_headers=True,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ultron-core")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check-config").set_defaults(func=_check_config)

    p = sub.add_parser("migrate")
    p.add_argument("--revision", default="head")
    p.set_defaults(func=_migrate)

    p = sub.add_parser("create-owner")
    p.add_argument("--email", required=True)
    p.add_argument("--display-name")
    p.set_defaults(func=_create_owner)

    p = sub.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=_serve)

    args = parser.parse_args(argv)
    if args.command in ("migrate", "create-owner"):
        from ultron_core.logging_setup import configure_logging

        settings = get_settings()
        configure_logging(settings.log_level, settings.log_format)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
