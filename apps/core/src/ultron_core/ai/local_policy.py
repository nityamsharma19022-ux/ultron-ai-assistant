"""Keeps local AI local.

Ollama has no authentication, so ULTRON only talks to it on this machine
(or the Docker host / Compose service) unless a secured remote setup is
deliberately enabled with ULTRON_OLLAMA_ALLOW_REMOTE=true and https.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from ultron_core.config import Settings

# Addresses that stay on the user's own machine.
LOCAL_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "host.docker.internal", "ollama", "ultron-ollama"}
)


def ollama_address_problem(settings: Settings) -> str | None:
    """Return why the configured Ollama address may not be used, or None."""
    url = (settings.ollama_base_url or "").strip()
    if not url:
        return None  # simply not configured
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return "ULTRON_OLLAMA_BASE_URL is not a valid http(s) address"
    remote_ok = settings.ollama_allow_remote and parts.scheme == "https"
    if settings.deployment == "cloud":
        if remote_ok:
            return None
        return (
            "local AI is disabled on a cloud backend (only enable a remote Ollama "
            "deliberately: ULTRON_OLLAMA_ALLOW_REMOTE=true with an https address)"
        )
    if host in LOCAL_HOSTS or remote_ok:
        return None
    return (
        f"Ollama address '{host}' is not on this machine; use 127.0.0.1 "
        "(or host.docker.internal from Docker), or set ULTRON_OLLAMA_ALLOW_REMOTE=true "
        "with an https address for a secured remote setup"
    )
