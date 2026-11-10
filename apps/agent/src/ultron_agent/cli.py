"""Command line: ultron-agent init | login | check | run | undo."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path

import httpx

from ultron_agent import __version__, credentials
from ultron_agent import config as config_mod
from ultron_agent.client import AuthError, CoreClient
from ultron_agent.runner import CERT_HINT, capabilities, is_certificate_error, run
from ultron_agent.tools import files, registry

EXAMPLE = Path(__file__).resolve().parents[2] / "agent.example.toml"


def _load(args: argparse.Namespace) -> config_mod.AgentConfig:
    try:
        return config_mod.load(Path(args.config) if args.config else None)
    except config_mod.ConfigError as exc:
        sys.exit(f"Config problem: {exc}")


def cmd_init(args: argparse.Namespace) -> None:
    target = Path(args.config) if args.config else config_mod.default_config_path()
    if target.exists():
        sys.exit(f"{target} already exists; edit it instead.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Created {target}\nEdit it (folders, apps, workflows), then run: ultron-agent login")


def cmd_login(args: argparse.Namespace) -> None:
    config = _load(args)
    email = args.email or input("ULTRON email: ")
    password = getpass.getpass("ULTRON password: ")
    client = _client(config)
    try:
        client.login(email, password, config.device_name)
    except AuthError as exc:
        sys.exit(f"Sign-in failed: {exc}")
    finally:
        client.close()
    print(f"Signed in as '{config.device_name}'. Start the agent with: ultron-agent run")


def _client(config: config_mod.AgentConfig) -> CoreClient:
    return CoreClient(
        config.server_url, config.data_dir, verify=str(config.ca_file) if config.ca_file else True
    )


def cmd_pair(args: argparse.Namespace) -> None:
    config = _load(args)
    code = args.code or input("Pairing code (System → Devices → Pair a device): ")
    client = _client(config)
    try:
        client.pair(code, config.device_name)
    except AuthError as exc:
        sys.exit(f"Pairing failed: {exc}")
    finally:
        client.close()
    print(f"Paired as '{config.device_name}'. Start the agent with: ultron-agent run")


def cmd_check(args: argparse.Namespace) -> None:
    config = _load(args)
    print(f"ULTRON agent {__version__}\nServer: {config.server_url}\nDevice: {config.device_name}")
    print("Folders:")
    for name, root in sorted(config.roots.items()):
        print(f"  {name:12} {root}  {'OK' if root.is_dir() else 'MISSING'}")
    print("Apps:      " + (", ".join(a.name for a in config.apps.values()) or "none"))
    print("Workflows: " + (", ".join(w.name for w in config.workflows.values()) or "none"))
    print("Tools:     " + ", ".join(registry.enabled(config)))
    print(
        "Signed in: " + ("yes" if credentials.load(config.data_dir) else "no (ultron-agent login)")
    )
    print("Announces: " + str(capabilities(config)))


def cmd_run(args: argparse.Namespace) -> None:
    config = _load(args)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"
    )
    client = _client(config)
    try:
        run(config, client, once=args.once)
    except AuthError as exc:
        sys.exit(str(exc))
    except httpx.HTTPError as exc:
        sys.exit(CERT_HINT if is_certificate_error(exc) else f"Can't reach ULTRON Core: {exc}")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        client.close()


def cmd_undo(args: argparse.Namespace) -> None:
    config = _load(args)
    undo_dir = config.data_dir / "undo"
    journals = sorted(undo_dir.glob("organize-*.json")) if undo_dir.exists() else []
    if not journals:
        sys.exit("Nothing to undo.")
    name = args.journal or journals[-1].name
    print(f"Restored {files.undo_organize(config, name)} files from {name}")


def cmd_logout(args: argparse.Namespace) -> None:
    config = _load(args)
    credentials.clear(config.data_dir)
    print("Signed out on this PC (also remove the device in ULTRON → System → Devices).")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ultron-agent", description="ULTRON Windows agent")
    parser.add_argument("--config", help="path to agent.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create agent.toml from the example").set_defaults(fn=cmd_init)
    login = sub.add_parser("login", help="sign this PC in to ULTRON Core")
    login.add_argument("--email")
    login.set_defaults(fn=cmd_login)
    pair = sub.add_parser("pair", help="sign this PC in with a pairing code")
    pair.add_argument("--code")
    pair.set_defaults(fn=cmd_pair)
    sub.add_parser("check", help="show what the agent may do").set_defaults(fn=cmd_check)
    runp = sub.add_parser("run", help="run the agent")
    runp.add_argument("--once", action="store_true", help="handle waiting work, then exit")
    runp.set_defaults(fn=cmd_run)
    undo = sub.add_parser("undo", help="undo the last 'organize'")
    undo.add_argument("journal", nargs="?")
    undo.set_defaults(fn=cmd_undo)
    sub.add_parser("logout", help="forget this PC's sign-in").set_defaults(fn=cmd_logout)
    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
