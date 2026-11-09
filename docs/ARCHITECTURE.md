# ULTRON Architecture

> **Status: APPROVED (2026-11-09).** Phase 1 (backend foundation) is
> built and tested — see [`PROJECT_STATUS.md`](../PROJECT_STATUS.md).
> Decisions are recorded in [`docs/adr/`](adr/); connectivity, offline mode
> and sync are specified in [`docs/SYNC.md`](SYNC.md).

ULTRON is an advanced personal AI assistant for **Android** and **Windows**.

## 1. Guiding principles

1. **Free and open source first.** Every required component is free/OSS.
   Paid services are optional add-ons, never required.
2. **Cloud-first, local-fallback.** Use cloud resources when they're
   available and within free limits; fall back to local resources
   automatically when they aren't (offline, rate-limited, quota used,
   or the request is marked private).
3. **Local by default during development.** PostgreSQL and Redis run in
   Docker Compose on the developer machine. No cloud account is needed to
   start.
4. **Supabase is optional.** ULTRON talks to plain PostgreSQL. A dedicated
   ULTRON Supabase project can be plugged in later as the cloud database.
5. **Separate databases, no automatic switching.** Local and cloud database
   settings are separate; exactly one is used, chosen by config. Moving data
   follows the sync strategy in [SYNC.md](SYNC.md).
6. **Strict project isolation.** ULTRON shares no database, deployment,
   credentials or environment variables with any other project
   ([ADR-0004](adr/0004-project-isolation.md)).

## 2. System overview

```mermaid
flowchart LR
    subgraph Devices
        A[ULTRON App<br/>Android]
        W[ULTRON App<br/>Windows]
    end

    subgraph Core["ULTRON Core (backend)"]
        API[API gateway<br/>REST + WebSocket]
        ORCH[Assistant orchestrator]
        ROUTER[AI provider router]
        MEM[Memory service]
        WORK[Background workers]
        VOICE[Speech service]
    end

    subgraph Data
        PG[(PostgreSQL 17<br/>+ pgvector)]
        RD[(Redis)]
        FS[(File storage)]
    end

    subgraph AI
        CLOUD[Cloud LLMs<br/>free tiers first]
        LOCAL[Local LLM<br/>Ollama]
    end

    A & W -->|HTTPS / WSS| API
    API --> ORCH
    ORCH --> ROUTER
    ORCH --> MEM
    ORCH --> VOICE
    ORCH --> WORK
    ROUTER -->|1st choice| CLOUD
    ROUTER -.->|fallback| LOCAL
    MEM --> PG
    WORK --> RD
    API --> RD
    ORCH --> FS
```

## 3. Components

### 3.1 ULTRON App (client)
- **One codebase for Android and Windows** using Flutter.
- Chat UI, voice input/output, notifications, settings.
- **Local SQLite cache** (via `drift`) holds recent conversations, settings
  and an **outbox** of actions taken while offline, synced when back online.
- Talks to ULTRON Core over HTTPS (REST) and WebSocket (streamed replies).

### 3.2 ULTRON Core (backend)
Python 3.12 + FastAPI, one deployable service plus a worker process.

| Module | Responsibility |
|---|---|
| API gateway | REST + WebSocket endpoints, auth, rate limiting (Redis) |
| Assistant orchestrator | Conversation flow, tool/skill calling, context assembly |
| AI provider router | Chooses a model provider per request; handles fallback |
| Memory service | Long-term memory: facts, notes, embeddings (pgvector) |
| Speech service | Speech-to-text and text-to-speech |
| Background workers | Reminders, scheduled tasks, long jobs (Redis-backed queue) |

### 3.3 Data layer

| Store | Used for | Local (now) | Cloud (later, optional) |
|---|---|---|---|
| PostgreSQL 17 + pgvector | Users, devices, conversations, memory, tasks | Docker Compose | New ULTRON-only Supabase project |
| Redis | Cache, rate limits, job queue, pub/sub for streaming, short-term context | Docker Compose | Any Redis-compatible host |
| File storage | Voice clips, attachments | Local folder / volume | S3-compatible (e.g. Supabase Storage) |
| SQLite (on device) | Offline cache + outbox | In the app | — |

**Schema management:** SQLAlchemy 2 + Alembic migrations. The same
migrations run against local Postgres and a future Supabase project — this
is what keeps Supabase optional. Migrations never run against the cloud
database unless `ULTRON_ALLOW_CLOUD_MIGRATIONS=true` is set for that command.

### 3.4 AI provider router
A single interface (`generate`, `stream`, `embed`, `transcribe`) with
pluggable providers, tried in a configurable order:

1. **Cloud, free tier** — e.g. Google Gemini API, Groq, OpenRouter free
   models (each optional, enabled only when its key is set).
2. **Cloud, paid (optional)** — e.g. Anthropic Claude, OpenAI. Off unless
   configured.
3. **Local fallback** — Ollama with an open-weight model
   (e.g. Llama / Qwen / Gemma; check each model's licence).

Fallback triggers: no network, timeout, HTTP 429 / quota exhausted,
provider error, or request flagged **private** (private requests go
local-only and never leave the machine). Free-tier limits change often, so
the router treats them as runtime signals rather than hard-coded numbers.

### 3.5 Speech
- Speech-to-text: **faster-whisper** (MIT), runs locally; cloud STT optional.
- Text-to-speech: **Piper** (open source; verify the current fork's licence
  at adoption); Android/Windows built-in TTS as zero-cost fallback.

## 4. Cloud-first, local-fallback in practice

| Layer | Cloud (preferred) | Local fallback |
|---|---|---|
| AI inference | Cloud LLM providers (free tiers first) | Ollama on the Windows PC / server |
| Backend reachability | Cloud-hosted ULTRON Core (future) | Windows local backend on the LAN → then on-device offline mode |
| Data | Supabase ULTRON project (future, optional) | Local Docker Postgres + Redis (current default) |
| Client data | Server is source of truth | SQLite cache + outbox, synced on reconnect |

**Databases never fail over automatically.** `ULTRON_DB_MODE` picks **one**
database per backend. Offline resilience comes from device caches and
outboxes, synced with idempotent operations when connectivity returns
([SYNC.md](SYNC.md), [ADR-0005](adr/0005-sync-and-no-automatic-db-switching.md)).

**Platform notes**
- *Windows:* runs the full local backend (Docker Desktop: Postgres, Redis,
  ULTRON Core) and local AI models (Ollama, native install recommended for
  GPU, or the `local-ai` Compose profile).
- *Android:* cannot run Docker. Its fallback is the PC/LAN backend, then
  offline mode (cached data, queued actions, on-device TTS/STT). An
  on-device small model can be evaluated later.

## 5. Configuration & secrets
- All settings come from environment variables prefixed `ULTRON_`.
- `.env.example` (committed, placeholders only) → copy to `.env`
  (git-ignored).
- `ULTRON_DB_MODE=local|cloud` selects the database
  (`ULTRON_LOCAL_DATABASE_URL` / `ULTRON_CLOUD_DATABASE_URL`).
- No secrets in code, Docker images, or git history.

## 6. Security (single-user personal assistant)
- One owner account created from the CLI; Argon2id password hashing.
- Per-device short-lived JWT access tokens + rotating refresh tokens with
  reuse detection; devices can be revoked instantly
  ([ADR-0006](adr/0006-authentication.md)).
- Login rate limiting in Redis.
- Local services bind to `127.0.0.1` only; LAN exposure for the Android
  app will be designed explicitly in Phase 3.
- Private-mode requests never reach cloud providers.
- Row-level security policies added if/when Supabase is connected.

## 7. Technology choices (free / open source)

| Concern | Choice | Licence |
|---|---|---|
| Client (Android + Windows) | Flutter / Dart | BSD-3-Clause |
| On-device storage | SQLite + drift | Public domain / MIT |
| Backend | Python 3.12, FastAPI | PSF / MIT |
| ORM + migrations | SQLAlchemy 2, Alembic | MIT |
| Database | PostgreSQL 17 + pgvector | PostgreSQL Licence |
| Cache / queue | Redis 8 (or Valkey, drop-in) | AGPLv3 option (Valkey: BSD) |
| Job queue | arq | MIT |
| Local LLM runtime | Ollama | MIT |
| Speech-to-text | faster-whisper | MIT |
| Text-to-speech | Piper | Open source |
| Containers | Docker Compose | Apache-2.0 |
| CI | GitHub Actions | Free tier |

## 8. Planned repository layout

```
ultron-ai-assistant/
├── apps/
│   ├── core/                 # ULTRON Core backend (Python, FastAPI)  [Phase 1 ✓]
│   │   ├── src/ultron_core/  # app, config, auth, db, migrations
│   │   ├── tests/            # unit + integration tests
│   │   └── Dockerfile
│   └── client/               # ULTRON App (Flutter: Android + Windows) [Phase 3]
├── infra/postgres/init/      # Local DB bootstrap (extensions only)
├── docs/                     # Architecture, sync design, ADRs, setup
├── .github/workflows/        # CI (lint, tests, image build)
├── docker-compose.yml        # Local backend: Postgres, Redis, Core (+ Ollama)
├── .env.example              # ULTRON-only config template
└── PROJECT_STATUS.md         # Current phase and test results
```

## 9. Delivery phases

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation: docs, Docker Compose (Postgres + Redis), env template, repo hygiene | **Done** |
| 1 | ULTRON Core: config, health, Postgres, Redis, migrations, auth, logging, tests, CI, Docker | **Done** |
| 2 | AI provider router (cloud free tier → Ollama fallback) + basic chat API with streaming | Next (awaiting go-ahead) |
| 3 | Flutter app (Windows + Android): chat UI, device pairing, backend selection, offline cache/outbox, sync endpoints | — |
| 4 | Long-term memory (pgvector), voice (STT/TTS), reminders/workers | — |
| 5 | Optional: connect a new ULTRON Supabase project; choose cloud hosting (not Netlify) | — |

## 10. Explicitly out of scope (by decision)
- Creating a Supabase project now.
- Any access to, or reuse of, other projects' Supabase or Netlify resources.
- Deploying ULTRON to Netlify, or using Netlify at all.
- Automatic switching between databases.
