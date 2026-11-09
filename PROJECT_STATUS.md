# ULTRON — Project status

_Last updated: 2026-11-09_

| Phase | Scope | Status |
|---|---|---|
| 0 | Architecture docs, Docker Compose (Postgres + Redis), env template | ✅ Done |
| 1 | ULTRON Core backend foundation | ✅ **Done — tested** |
| 2 | AI provider router (cloud free tier → Ollama fallback) + chat API | ⏸ Not started (awaiting go-ahead) |
| 3 | Flutter app (Android + Windows), pairing, offline cache/outbox, sync endpoints | — |
| 4 | Memory (pgvector), voice, reminders/workers | — |
| 5 | Optional ULTRON-only Supabase project, cloud hosting (not Netlify), edge role | — |

## Phase 1 — what was built

| Requirement | Implementation |
|---|---|
| FastAPI backend skeleton | `apps/core` — app factory, lifespan, `/api/v1` router, CLI (`ultron-core`) |
| Configuration management | `pydantic-settings`, `ULTRON_`-prefixed only; separate `ULTRON_LOCAL_DATABASE_URL` / `ULTRON_CLOUD_DATABASE_URL`; `ULTRON_DB_MODE` selects one, **no automatic fallback** |
| Health checks | `/health/live` (identifies node: `deployment`, `node_id`, `api_version`), `/health/ready` (Postgres + schema version + Redis → 200/503; local AI reported, optional) |
| PostgreSQL connection | SQLAlchemy 2.1 async + asyncpg, pre-ping, connect timeout, lazy connect (app starts and reports `not_ready` if DB is down) |
| Redis connection | redis-py 8 asyncio, timeouts, `ultron:` key namespace |
| Database migrations | Alembic (async); migration `0001` = users, devices, refresh_tokens; auto-applied in Docker for the **local** DB only; cloud migrations need `ULTRON_ALLOW_CLOUD_MIGRATIONS=true` |
| Basic authentication | Single owner (CLI-created), Argon2id hashes, per-device JWT access tokens (15 min), rotating refresh tokens with reuse detection, device list/revoke, logout, Redis login rate limiting |
| Structured logging | structlog: console or JSON, request id (`X-Request-ID`), one line per request, stdlib/uvicorn unified, secrets redacted |
| Automated tests | 49 pytest tests (unit + integration against real Postgres/Redis), ruff lint/format; GitHub Actions workflow |
| Docker Compose | `postgres`, `redis`, `core` (built from `apps/core/Dockerfile`, non-root, healthcheck), optional `ollama` (`local-ai` profile) |
| Environment example | `.env.example` updated (DB selection, auth, LAN binding, local AI) |

Also delivered: [docs/SYNC.md](docs/SYNC.md) (cloud-first → Windows local →
offline connectivity, Android offline features, outbox + change-feed sync,
conflict policy, safe local→cloud move), ADR-0005 (sync / no automatic
DB switching), ADR-0006 (authentication).

## Test results (2026-11-09)

Environment: local Docker stack (PostgreSQL 17.11 + pgvector 0.8.7,
Redis 8.10.3), Python 3.13.

```
ruff check  → All checks passed
ruff format → 33 files already formatted
pytest      → 49 passed (22 unit, 27 integration)
```

| Test file | Tests | Covers |
|---|---|---|
| `test_config.py` | 10 | local/cloud separation, **no fallback** either way, only `ULTRON_*` vars read, secret validation, secrets hidden in repr |
| `test_security.py` | 8 | Argon2 hashing; JWT expiry, wrong secret/audience/type, `alg=none` rejected |
| `test_logging.py` | 3 | JSON structure, stdlib logs unified, secret redaction |
| `test_cli.py` | 1 | `check-config` hides passwords/secrets |
| `test_health.py` | 7 | live/ready, 503 when DB or Redis down **without switching DB**, local AI optional, request ids |
| `test_auth.py` | 16 | login/me, enumeration-safe errors, token rotation, reuse → family revoked, logout, device revoke, rate limit (429), inactive user, single owner, password policy |
| `test_migrations.py` | 4 | models match migrations, downgrade/upgrade round trip, cloud migrations blocked |

End-to-end check with `docker compose up` (full stack): all containers
healthy; migrations applied on start (and safely re-run on restart);
`/health/ready` → 200; owner created via CLI; second owner refused; login
and `/auth/me` work; password never appears in logs; cloud mode skips
automatic migrations.

GitHub Actions CI (run #1, commit `558a3e6`): ✅ **success**: lint +
49 tests on fresh Postgres/Redis services, and the Docker image built from
the committed Dockerfile.
<https://github.com/nityamsharma19022-ux/ultron-ai-assistant/actions/runs/42622453068>

### Issues found and fixed during testing
- Owner accounts with private domains (e.g. `me@ultron.local`) could be
  created but not log in (login used strict email validation). Both now use
  the same rule; regression tests added.
- Health-probe requests flooded INFO logs every 10 s → now logged at DEBUG.

## Known limitations / notes
- **Docker image in this sandbox:** Docker Hub rate-limited this cloud
  sandbox and its HTTPS proxy needs a custom CA, so the image was built with
  a temporary copy of the Dockerfile that only adds that CA in the build
  stage. The committed `apps/core/Dockerfile` is unchanged, and GitHub
  Actions built it successfully (see below).
- **Windows:** the PowerShell steps in `docs/DEVELOPMENT.md` haven't been
  run on a real Windows machine yet (this sandbox runs Linux).
- Sync endpoints, client outbox and LAN TLS pinning are designed
  ([SYNC.md](docs/SYNC.md)), not yet implemented (Phase 3).
- No Supabase project created; Netlify not used; no other project's
  resources accessed.

## Next step
Phase 2 (AI provider router + chat API) starts only after Phase 1 is reviewed
and approved.
