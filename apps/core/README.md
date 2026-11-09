# ULTRON Core

The ULTRON backend: Python 3.13, FastAPI, SQLAlchemy 2 (asyncpg), Alembic,
Redis, structlog.

```
src/ultron_core/
├── main.py            # app factory + lifespan (DB engine, Redis, HTTP client)
├── config.py          # ULTRON_* settings; one database, no automatic fallback
├── logging_setup.py   # structured logging (console or JSON), secret redaction
├── middleware.py      # request id + one log line per request
├── deps.py            # FastAPI dependencies (settings, session, redis, auth)
├── api/health.py      # /health/live, /health/ready
├── auth/              # owner login, devices, JWT + rotating refresh tokens
├── ai/                # provider adapters, cloud-first router, cooldowns, context
├── chat/              # conversations, messages, streaming, cancellation
├── db/                # models, engine, migration helpers
├── migrations/        # Alembic (async)
└── cli.py             # ultron-core check-config | migrate | create-owner | serve
```

## Endpoints (v1)

| Method | Path | Auth |
|---|---|---|
| GET | `/health/live` | — |
| GET | `/health/ready` | — |
| POST | `/api/v1/auth/login` | — |
| POST | `/api/v1/auth/refresh` | — |
| POST | `/api/v1/auth/logout` | Bearer |
| GET | `/api/v1/auth/me` | Bearer |
| GET | `/api/v1/devices` | Bearer |
| DELETE | `/api/v1/devices/{id}` | Bearer |
| POST / GET | `/api/v1/conversations` | Bearer |
| GET / PATCH / DELETE | `/api/v1/conversations/{id}` | Bearer |
| POST | `/api/v1/conversations/{id}/messages` (JSON or SSE) | Bearer |
| POST | `/api/v1/conversations/{id}/cancel` | Bearer |
| GET | `/api/v1/ai/status` | Bearer |
| GET / PUT | `/api/v1/ai/preferences` | Bearer |

Setup, tests and Windows instructions: [docs/DEVELOPMENT.md](../../docs/DEVELOPMENT.md).
