# ADR-0002: Local PostgreSQL + Redis via Docker Compose; Supabase optional

- **Status:** Accepted (requested by project owner)
- **Date:** 2026-11-09

## Context
ULTRON needs a database and cache for development without creating cloud
projects or reusing any other project's Supabase instance.

## Decision
- Run **PostgreSQL 17 + pgvector** and **Redis** locally with Docker
  Compose (`docker-compose.yml`), namespaced to ULTRON and bound to
  `127.0.0.1`.
- PostgreSQL 17 matches Supabase's current major version, and pgvector /
  pg_trgm are available on both.
- The backend depends only on standard PostgreSQL. Schema changes are
  Alembic migrations that run unchanged on local Postgres or Supabase.
- Supabase integration is **off by default** (`ULTRON_DB_MODE=local`).
  When wanted, a **new, ULTRON-only** Supabase project is created and its
  values go into `ULTRON_SUPABASE_*` variables.

## Consequences
- No Supabase-only features (Auth, Realtime, Storage) are required by the
  core; they can be adopted later behind interfaces.
- Developers need Docker (Docker Desktop on Windows).
