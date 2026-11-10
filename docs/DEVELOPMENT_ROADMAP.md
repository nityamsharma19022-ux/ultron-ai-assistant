# ULTRON development roadmap

Each phase is built, tested and reported, and the next one starts only after
the owner approves. Status detail: [PROJECT_STATUS.md](../PROJECT_STATUS.md).

| Phase | Name | Status |
|---|---|---|
| 0 | Foundation | ✅ Done |
| 1 | Backend foundation (ULTRON Core) | ✅ Done |
| 2 | Intelligence Engine: AI router + chat API | ✅ Done, awaiting review |
| 3 | ULTRON App (Flutter: Android + Windows) + sync | ⏸ Needs approval |
| 4 | Memory, voice, reminders | — |
| 5 | Cloud (optional): ULTRON-only Supabase, hosting, edge role | — |

## Phase 0 — Foundation ✅
Architecture docs and decision records, Docker Compose (PostgreSQL 17 +
pgvector, Redis), `ULTRON_`-only env template, repo hygiene.

## Phase 1 — Backend foundation ✅
FastAPI app, configuration (separate local/cloud DB, no automatic switching),
health checks, Postgres + Redis, Alembic migrations, owner/device auth,
structured logging, tests, CI, Docker image.

## Phase 2 — Intelligence Engine ✅
- Provider-independent adapters: OpenAI-compatible (Groq, Gemini,
  OpenRouter, custom), Anthropic (official SDK), Ollama (local), dev mock.
- Cloud-first, local-fallback router: preferences, cooldowns for rate
  limits/quota/outages, offline detection, private → local only, honest
  local-model detection.
- Chat API: conversations, history, context trimming, streaming (SSE),
  cancellation, rate limits, validation.
- `docs/SECURITY.md`, ADR-0007.

## Phase 3 — ULTRON App (premium interface) ✅ built, device builds pending
- Flutter app for Windows and Android ([apps/client](../apps/client/README.md)):
  sign-in, conversation list, streaming chat with stages and cloud/local
  badge, private toggle, stop/retry; animated AI visualizer; system
  dashboard (status, local model warm-up, devices); settings (AI routing,
  appearance, voice, account).
- Voice with the platform's own engines: push-to-talk and read-aloud, with
  privacy rules for private conversations ([SECURITY.md](SECURITY.md)).

## Phase 3b — Offline and pairing (deferred)
- Backend selection on Android: cloud → Windows local backend → offline
  ([SYNC.md](SYNC.md)); pairing with TLS certificate pinning for LAN.
- Offline mode: SQLite cache (drift) + outbox; "ask later" queue.
- Sync endpoints on the backend: `sync_applied_ops`, change feed by `seq`,
  idempotent push, conflict copies. Private conversations excluded from
  any cloud sync.
- Optional: on-device small model evaluation for Android.

## Phase 4 — Memory, voice, reminders
- Long-term memory with pgvector embeddings (local embedding model by
  default; private data embedded locally only).
- Voice upgrade: faster-whisper speech-to-text and Piper text-to-speech on
  the Windows backend (local, so Android private chats can use voice too).
  Phase 3 already has push-to-talk and read-aloud with platform engines.
- Reminders and background jobs (Redis queue), delivered to devices.
- Action framework design (allow-listed, user-confirmed) with its own
  security review. No AI-triggered actions before this.

## Phase 5 — Cloud (optional)
- New ULTRON-only Supabase project (cloud database) via the documented
  migration procedure; no automatic database switching.
- Cloud hosting for ULTRON Core (not Netlify), free tier first.
- Windows backend becomes an edge node; device re-pairing.
- Multi-process concerns: Redis-based cancellation and generation locks.

## Cross-cutting rules
- Free and open source first; paid services optional only.
- No access to, or reuse of, other projects' resources.
- Every phase: tests (no paid API usage), docs, status report.
