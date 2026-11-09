# ULTRON — instructions for Claude Code

Personal AI assistant for Android and Windows. Owner: nityamsharma19022-ux.
Read `PROJECT_STATUS.md` first, then `docs/ARCHITECTURE.md`.

## Where things are
- Local project folder (Windows): `D:\ULTRON\ultron-ai-assistant`
- GitHub: `https://github.com/nityamsharma19022-ux/ultron-ai-assistant`
- Development branch: `claude/fervent-lovelace-fqank5`. `main` holds only the
  initial README until this branch is merged.
- Backend: `apps/core` (Python 3.13, FastAPI, SQLAlchemy + Alembic, Redis).
- Frontend: none yet (Flutter app is Phase 3, not started).
- Local stack: `docker-compose.yml` (postgres, redis, core, optional ollama).

## Commands (from `apps/core`)
- Tests: `uv run pytest` (Postgres + Redis must be up: `docker compose up -d postgres redis`)
- Unit tests only: `uv run pytest -m "not integration and not ollama_live"`
- Lint: `uv run ruff check src tests` and `uv run ruff format --check src tests`
- Live Ollama tests: set `ULTRON_TEST_OLLAMA_URL` / `ULTRON_TEST_OLLAMA_MODEL`, then `uv run pytest -m ollama_live`
- Windows checks: `scripts/windows/Test-UltronOllama.ps1`, `scripts/windows/Invoke-UltronEnvironmentAudit.ps1`

## Rules
- Work phase by phase; start a new phase only after the owner approves it.
- Never push, merge, reset or force-push without the owner's approval.
- Never commit `.env` or print secrets; all settings are `ULTRON_`-prefixed.
- ULTRON is isolated: never use or change other projects' resources (no
  existing Supabase project, no Netlify). Cloud database = a future,
  ULTRON-only project.
- Free/open-source first; tests use fake providers or mocked HTTP, never
  paid API calls.
- Cloud-first, local-fallback AI; private conversations use local AI only;
  Ollama only at local addresses (`127.0.0.1` / `host.docker.internal`);
  AI output is text only and never executed.
- No automatic database switching (`docs/SYNC.md`).
- Update `PROJECT_STATUS.md` with real results after each piece of work.
