"""Agent configuration (TOML, kept outside Git).

Everything the agent may touch is listed here by the user:

- ``[roots]``: named folders. File tools only work inside these.
- ``[apps]``: named apps and how to start them.
- ``[workflows]``: named sequences of commands (no shell).

Default location: ``.ultron-agent/agent.toml`` in the ULTRON project folder
(git-ignored), or the path in ULTRON_AGENT_CONFIG.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass
class AppEntry:
    name: str
    command: list[str]
    window_title: str | None = None


@dataclass
class Workflow:
    name: str
    commands: list[list[str]]
    cwd: str | None = None  # root-relative, e.g. "ultron/apps/core"
    timeout_seconds: int = 600
    open_apps: list[str] = field(default_factory=list)


@dataclass
class AgentConfig:
    server_url: str
    device_name: str
    data_dir: Path
    roots: dict[str, Path]
    apps: dict[str, AppEntry]
    workflows: dict[str, Workflow]
    poll_wait_seconds: int = 20
    # Core's own certificate (cert.pem from `ultron-core tls-init`) when it
    # uses HTTPS; None uses the system's trusted certificates.
    ca_file: Path | None = None
    max_read_bytes: int = 20 * 1024 * 1024
    disabled_tools: set[str] = field(default_factory=set)

    def app(self, name: str) -> AppEntry | None:
        key = name.strip().lower()
        if key in self.apps:
            return self.apps[key]
        matches = [a for k, a in self.apps.items() if key in k or k in key]
        return matches[0] if len(matches) == 1 else None

    def workflow(self, name: str) -> Workflow | None:
        return self.workflows.get(name.strip().lower())


def project_dir() -> Path:
    # apps/agent/src/ultron_agent/config.py -> project root
    return Path(__file__).resolve().parents[4]


def default_config_path() -> Path:
    env = os.environ.get("ULTRON_AGENT_CONFIG")
    return Path(env) if env else project_dir() / ".ultron-agent" / "agent.toml"


def _str_list(value: object, where: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where} must be a non-empty list of strings")
    return list(value)


def load(path: Path | None = None) -> AgentConfig:
    path = path or default_config_path()
    if not path.exists():
        raise ConfigError(f"No agent config at {path}. Run: ultron-agent init")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from None

    server = data.get("server", {})
    url = str(server.get("url", "")).rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ConfigError("[server] url must start with http:// or https://")
    ca_file = None
    if server.get("ca_file"):
        ca_file = Path(os.path.expandvars(os.path.expanduser(str(server["ca_file"]))))
        if not ca_file.is_file():
            raise ConfigError(f"[server] ca_file not found: {ca_file}")

    roots: dict[str, Path] = {}
    for name, value in data.get("roots", {}).items():
        key = name.strip().lower()
        if not key.isidentifier():
            raise ConfigError(f"Root name '{name}' must be a simple word")
        root = Path(os.path.expandvars(os.path.expanduser(str(value))))
        if not root.is_absolute():
            raise ConfigError(f"Root '{name}' must be an absolute path")
        roots[key] = root

    apps: dict[str, AppEntry] = {}
    for name, value in data.get("apps", {}).items():
        if isinstance(value, str):
            value = {"command": [value]}
        if not isinstance(value, dict):
            raise ConfigError(f"App '{name}' must be a path or a table")
        apps[name.strip().lower()] = AppEntry(
            name=name,
            command=_str_list(value.get("command"), f"apps.{name}.command"),
            window_title=value.get("window_title"),
        )

    workflows: dict[str, Workflow] = {}
    for name, value in data.get("workflows", {}).items():
        commands = value.get("commands", [])
        if not isinstance(commands, list) or not all(isinstance(c, list) for c in commands):
            raise ConfigError(f"workflows.{name}.commands must be a list of argument lists")
        workflows[name.strip().lower()] = Workflow(
            name=name,
            commands=[_str_list(c, f"workflows.{name}.commands") for c in commands],
            cwd=value.get("cwd"),
            timeout_seconds=int(value.get("timeout_seconds", 600)),
            open_apps=list(value.get("open_apps", [])),
        )
        if not commands and not workflows[name.strip().lower()].open_apps:
            raise ConfigError(f"Workflow '{name}' has nothing to do")

    agent = data.get("agent", {})
    data_dir = Path(agent.get("data_dir") or path.parent)
    return AgentConfig(
        server_url=url,
        device_name=str(agent.get("device_name") or os.environ.get("COMPUTERNAME") or "Windows PC"),
        data_dir=data_dir,
        roots=roots,
        apps=apps,
        workflows=workflows,
        poll_wait_seconds=int(agent.get("poll_wait_seconds", 20)),
        disabled_tools=set(agent.get("disabled_tools", [])),
        ca_file=ca_file,
    )
