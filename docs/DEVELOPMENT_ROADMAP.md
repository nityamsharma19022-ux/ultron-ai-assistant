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

## Phase 3 — ULTRON App + sync (proposed)
- Flutter app for Windows and Android: login/pairing, conversation list,
  streaming chat UI with cloud/local badge, private toggle, AI status and
  preferences screens, cancel button.
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
- Voice: faster-whisper speech-to-text, Piper text-to-speech, platform TTS
  fallback.
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
