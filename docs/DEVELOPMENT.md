# ULTRON local development

Phase 0 gives you a local PostgreSQL + Redis stack for ULTRON. No cloud
account is needed.

## Prerequisites
- **Docker** — Docker Desktop on Windows (WSL 2 backend) or Docker Engine
  on Linux. Docker Compose v2 is included.
- **Git**

## 1. Create your ULTRON `.env`

macOS / Linux / Git Bash:
```bash
cp .env.example .env
```

Windows PowerShell:
```powershell
Copy-Item .env.example .env
```

Open `.env` and replace `change-me-postgres` and `change-me-redis` with
your own passwords (in the password fields **and** in the two `_URL` lines).
`.env` is git-ignored; never commit it.

## 2. Start the stack

```bash
docker compose up -d
```

```bash
docker compose ps
```

Both `ultron-postgres` and `ultron-redis` should show `healthy`.

## 3. Check the services

PostgreSQL (should list `vector` and `pg_trgm`):
```bash
docker compose exec postgres psql -U ultron -d ultron -c "\dx"
```

Redis (should reply `PONG`):
```bash
docker compose exec redis redis-cli ping
```

From your host, the services are at:

| Service | Address |
|---|---|
| PostgreSQL | `localhost:5433` (database `ultron`, user `ultron`) |
| Redis | `localhost:6380` |

Both listen on `127.0.0.1` only.

## 4. Stop / reset

Stop (keeps data):
```bash
docker compose down
```

Delete **all ULTRON local data** (only ULTRON volumes are affected):
```bash
docker compose down -v
```

## Using Valkey instead of Redis
Add to `.env`:
```
ULTRON_REDIS_IMAGE=valkey/valkey:8-alpine
ULTRON_REDIS_SERVER_CMD=valkey-server
```

## Connecting Supabase later (optional)
1. Create a **new** Supabase project dedicated to ULTRON (never reuse
   another project's).
2. Fill the `ULTRON_SUPABASE_*` values in `.env`.
3. Set `ULTRON_DB_MODE=supabase`.
4. Run the same migrations used locally.
