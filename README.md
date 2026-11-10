# ULTRON

Advanced personal AI assistant for **Android** and **Windows**.

> **Status:** Phase 3 built — the ULTRON app for Windows and Android
> (chat, AI visualizer, dashboard, settings, voice) on top of the
> cloud-first / local-fallback backend. See
> [PROJECT_STATUS.md](PROJECT_STATUS.md) and the
> [roadmap](docs/DEVELOPMENT_ROADMAP.md).

## Principles
- **Free and open source first** — no paid service is required.
- **Cloud-first, local-fallback** — cloud AI and services when available,
  automatic fallback to local models and services when not.
- **Local development by default** — PostgreSQL + Redis in Docker Compose.
- **Supabase optional** — a dedicated ULTRON project can be connected later.
- **Fully isolated** — no shared config, data, credentials or deployments
  with any other project.

## Stack
Flutter (Android + Windows) · Python/FastAPI · PostgreSQL 17 + pgvector ·
Redis · Ollama (local AI) — all free and open source.

## Quick start
```bash
cp .env.example .env    # then set your own passwords and JWT secret
docker compose up -d --build
curl http://localhost:8000/health/ready
```
Details: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). The app:
[apps/client/README.md](apps/client/README.md).

## Documentation
- [Architecture](docs/ARCHITECTURE.md)
- [Connectivity, offline mode & sync](docs/SYNC.md)
- [Security](docs/SECURITY.md)
- [Roadmap](docs/DEVELOPMENT_ROADMAP.md)
- [Local development](docs/DEVELOPMENT.md)
- [Project status](PROJECT_STATUS.md)
- [Architecture decision records](docs/adr/)
