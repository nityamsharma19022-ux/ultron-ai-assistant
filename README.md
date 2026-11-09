# ULTRON

Advanced personal AI assistant for **Android** and **Windows**.

> **Status:** Phase 0 — foundation. The architecture is **proposed** and
> awaiting approval before application features are built.

## Principles
- **Free and open source first** — no paid service is required.
- **Cloud-first, local-fallback** — cloud AI and services when available,
  automatic fallback to local models and services when not.
- **Local development by default** — PostgreSQL + Redis in Docker Compose.
- **Supabase optional** — a dedicated ULTRON project can be connected later.
- **Fully isolated** — no shared config, data, credentials or deployments
  with any other project.

## Quick start
```bash
cp .env.example .env    # then set your own passwords
docker compose up -d
docker compose ps
```
Details: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)

## Documentation
- [Architecture](docs/ARCHITECTURE.md)
- [Local development](docs/DEVELOPMENT.md)
- [Architecture decision records](docs/adr/)
