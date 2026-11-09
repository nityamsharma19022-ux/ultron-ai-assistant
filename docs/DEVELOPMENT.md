# ULTRON local development

The local backend (PostgreSQL, Redis, ULTRON Core and, optionally, a local
AI runtime) runs on your Windows PC. No cloud account is needed.

## Prerequisites
- **Docker Desktop** (Windows, WSL 2 backend) or Docker Engine (Linux).
- **Git**.
- For running the backend outside Docker or running tests:
  [uv](https://docs.astral.sh/uv/) (it installs Python 3.13 for you).
- Optional local AI: [Ollama](https://ollama.com) (native Windows install
  recommended for GPU access).

## 1. Create your ULTRON `.env`

PowerShell:
```powershell
Copy-Item .env.example .env
```

macOS / Linux / Git Bash:
```bash
cp .env.example .env
```

Then edit `.env`:
- Replace `change-me-postgres` and `change-me-redis` (in the password lines
  **and** the `_URL` lines). Use letters, digits, `-` and `_` only.
- Set `ULTRON_JWT_SECRET` to a random value:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```

`.env` is git-ignored. Never commit it.

## 2. Start the local backend (Docker)

```bash
docker compose up -d --build
```

```bash
docker compose ps
```

`ultron-postgres`, `ultron-redis` and `ultron-core` should all be `healthy`.
Migrations are applied automatically on start (local database only).

Check it:
```bash
curl http://localhost:8000/health/ready
```

API docs (development only): <http://localhost:8000/docs>

## 3. Create the owner account (once)

```bash
docker compose exec core ultron-core create-owner --email you@example.com
```

You'll be asked for a password (at least 12 characters). Then log in:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login -H "Content-Type: application/json" -d "{\"email\":\"you@example.com\",\"password\":\"YOUR-PASSWORD\",\"device_name\":\"My PC\",\"platform\":\"windows\"}"
```

## 4. Local AI on Windows (optional)

**Recommended — native Ollama:** install Ollama for Windows, then pull a model:
```powershell
ollama pull llama3.2
```
The Docker backend reaches it at `http://host.docker.internal:11434`
(already the default). `/health/ready` reports it under `checks.local_ai`.

**Alternative — Ollama in Docker:**
```bash
docker compose --profile local-ai up -d
```
and set `ULTRON_CORE_OLLAMA_BASE_URL=http://ollama:11434` in `.env`.

Local AI is optional: if it's missing, readiness still passes.

## 5. Run the backend without Docker (Windows native)

Keep Postgres and Redis in Docker:
```powershell
docker compose up -d postgres redis
```

Then, from `apps\core`:
```powershell
uv sync
```

```powershell
uv run ultron-core migrate
```

```powershell
uv run ultron-core serve --reload
```

This uses `ULTRON_LOCAL_DATABASE_URL`, `ULTRON_REDIS_URL` and
`ULTRON_OLLAMA_BASE_URL` (e.g. `http://localhost:11434`) from the root `.env`.

## 6. Let the Android app reach the Windows backend

By default the API listens on `127.0.0.1` (this PC only). For the phone on
the same Wi-Fi:

1. Set `ULTRON_CORE_BIND_HOST=0.0.0.0` in `.env` and run
   `docker compose up -d`.
2. Allow inbound TCP 8000 for **private** networks only in Windows Firewall.
3. Use `http://<your-PC-LAN-IP>:8000` in the app (Phase 3 adds pairing with
   certificate pinning).

PostgreSQL and Redis always stay on `127.0.0.1`.

## 7. Run the tests

With Postgres and Redis running (`docker compose up -d postgres redis`),
from `apps/core`:

```bash
uv run pytest
```

```bash
uv run ruff check src tests
```

Integration tests use a separate `ultron_test` database (recreated on every
run) and Redis keys prefixed `ultron-test:`. Your real data isn't touched.
Unit tests only: `uv run pytest -m "not integration"`.

## 8. Useful commands

| Task | Command |
|---|---|
| Show active config (no secrets) | `docker compose exec core ultron-core check-config` |
| Logs | `docker compose logs -f core` |
| New migration | `uv run alembic revision --autogenerate -m "describe change"` (in `apps/core`) |
| Stop (keep data) | `docker compose down` |
| Delete all ULTRON local data | `docker compose down -v` |

## Using Valkey instead of Redis
Add to `.env`:
```
ULTRON_REDIS_IMAGE=valkey/valkey:8-alpine
ULTRON_REDIS_SERVER_CMD=valkey-server
```

## Cloud database (later, optional)
See [SYNC.md §10](SYNC.md#10-moving-from-the-local-database-to-a-cloud-database-deliberate).
Never point ULTRON at another project's database.
