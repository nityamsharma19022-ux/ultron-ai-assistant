# ADR-0001: Cloud-first, local-fallback

- **Status:** Proposed
- **Date:** 2026-11-09

## Context
ULTRON must keep working when cloud services are unavailable, rate-limited
or over their free quota, and some requests are too private to send to a
third party.

## Decision
Every capability that can use a cloud resource has a local fallback,
selected automatically at runtime:

- **AI:** a provider router tries configured cloud providers (free tiers
  first), then falls back to a local Ollama model. Requests flagged private
  go local-only.
- **Backend:** the app tries the cloud backend URL, then a local/LAN
  backend URL, then offline mode.
- **Client data:** SQLite cache + outbox on the device, synced on reconnect.

The server uses **one** primary database chosen by `ULTRON_DB_MODE`; we do
not build automatic cloud↔local database failover.

## Consequences
- Provider-agnostic interfaces are required from day one.
- Local fallback quality depends on local hardware (GPU for Ollama).
- Android's fallback is limited to the LAN backend and offline mode.
