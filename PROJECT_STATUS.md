# ULTRON — Project status

_Last updated: 2026-11-10_

> **Round 3 (2026-11-10): FreeLLMAPI.** Core now uses your FreeLLMAPI
> gateway as its first cloud AI source (never for private chats), can test
> each AI source from the app, and shows AI usage per model. Full audit:
> [docs/ULTRON_STATUS_REPORT.md](docs/ULTRON_STATUS_REPORT.md); setup:
> [docs/FREELLMAPI.md](docs/FREELLMAPI.md).
>
> **Round 2 (2026-11-10): toward a personal AI operating system.** The app
> now opens on a **Command Center** (live devices, tasks, reminders,
> notifications, AI activity, autonomy; floating panels on desktop).
> New: autonomy levels 0–5 per area, operating modes, proactive
> notifications with quiet hours and a daily briefing, automatic safety
> pause, conversation search, project memories, pause memory saving, full
> data export, routing by task type, safe web reading, and new Windows
> agent tools (copy, rename, running programs, close app, open links,
> toasts, live metrics). Roadmap: [docs/ULTRON_ROADMAP.md](docs/ULTRON_ROADMAP.md);
> feature status: [docs/FEATURE_STATUS.md](docs/FEATURE_STATUS.md); log:
> [docs/DEVELOPMENT_LOG.md](docs/DEVELOPMENT_LOG.md); limitations:
> [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md); [CHANGELOG.md](CHANGELOG.md).
> Still needs your PC and phone for the device checks.
>
> **Master build (2026-11-10):** ULTRON now has memory, documents, an
> autonomous task engine with permissions, a Windows agent, an Android
> system assistant and secure pairing. Current state and test results:
> [docs/ULTRON_BUILD_STATUS.md](docs/ULTRON_BUILD_STATUS.md); release
> checklist: [docs/ULTRON_RELEASE_CHECKLIST.md](docs/ULTRON_RELEASE_CHECKLIST.md).

| Phase | Scope | Status |
|---|---|---|
| 0 | Architecture docs, Docker Compose (Postgres + Redis), env template | ✅ Done |
| 1 | ULTRON Core backend foundation | ✅ Done (CI green) |
| 2 | Intelligence Engine: AI provider router + chat API | ✅ Done (CI green) |
| 2.1 | Real Ollama integration (Windows, `qwen3.5:4b`) | 🟡 Built; real-model run pending on your PC |
| 2.2 | Local AI integration: loading states, warm-up, time limit, local-only guard | 🟡 **Built and tested in sandbox; real-model run pending on your PC** |
| 3 | Flutter app (Windows + Android): premium interface, chat, visualizer, dashboard, settings, voice | 🟡 **Built and tested in sandbox (web preview); Windows/Android builds pending on your PC** |
| 3b | Offline cache/outbox, sync endpoints, secure phone pairing (TLS) | ⏸ Deferred (approved plan) |
| 4 | Memory (pgvector), voice, reminders | — |
| 5 | Optional ULTRON-only Supabase project, cloud hosting (not Netlify), edge role | — |

Full plan: [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md).

---

## Phase 3 — Premium interface (2026-11-10)

Flutter app in `apps/client` (Flutter 3.47.9, Dart 3.13.7, Riverpod 3).
Built in five increments, each tested before the next. **The backend was
not changed** (no files under `apps/core` touched).

| Increment | What it does | Commit (local) |
|---|---|---|
| 3.1 Foundation | Dark futuristic theme (Orbitron + Inter, 5 accents), API client with token refresh, secure token storage, sign-in with connection test, responsive shell (sidebar ≥ 900 px, top bar + bottom nav on phones), cloud/local connection indicator, offline banner | `8745dcc` |
| 3.2 Chat | Streamed replies (SSE) with stage text, stop, retry, CLOUD/LOCAL badge with fallback note, conversation list, private conversations, copy | `ca24843` |
| 3.3 Visualizer | Animated core (rings, particles, reactive bars) with modes idle / listening / thinking / loading model / generating / speaking / offline; colours by AI source; Full / Reduced / Off motion | `a0e0940` |
| 3.4 Dashboard + settings | System status (Core, DB, Redis, AI sources, local model with warm-up, devices with sign-out); settings for AI routing (saved on Core), accent, motion, voice, account, licences | `13a24fe` |
| 3.5 Voice | Push-to-talk with live transcript, read-aloud, mic level → visualizer, privacy rules (below) | `bab902c` |

### Test results (this sandbox, 2026-11-10)
- **Flutter:** `flutter analyze` → no issues; `flutter test` → **74 passed**
  (fake ULTRON Core and fake speech engines; no network).
- **Backend:** `uv run pytest` → **162 passed, 11 skipped** (the skipped
  ones are the live-Ollama tests); ruff check and format clean.
- **Browser check against the real backend** (web build of the app, Docker
  stack with the dev mock cloud provider): sign-in, chat streaming with
  stages, visualizer, dashboard, settings and the voice controls all work
  on desktop (1280–1600 px) and phone (412 px) sizes. Headless Chromium
  even started real listening. Screenshots were sent with the report.
- Local AI showed "unavailable" in the sandbox because there is no Ollama
  here; that is expected.

### Voice and privacy
- Windows: speech recognition is Windows Speech (SAPI) on the PC; allowed
  in private conversations.
- Android: the recogniser may use an online service (the plugin's
  "on-device" option silently falls back), so **voice input is off in
  private conversations** there, with an explanation.
- Read-aloud in private conversations uses only offline voices (Android
  voices report whether they need the network); otherwise the app says the
  reply wasn't read.

### Bugs found and fixed during Phase 3
- Release Android builds were missing the INTERNET permission (debug
  builds hide this) and blocked plain HTTP to ULTRON Core. Fixed in the
  manifest; also added microphone permission and the app name "ULTRON".
- Panels drew without their dark fill (a gradient replaced the colour) and
  hid ink ripples; fixed in `GlassPanel`.
- `Stream.timeout` never finished under the test clock; replaced by a small
  idle-timeout helper with its own tests.
- A failed reply lost its error text, and new conversations kept the title
  "New conversation"; both fixed.

### Not verified here (needs your PC)
- `flutter run -d windows` / `flutter build windows` (needs Visual Studio's
  C++ workload; the sandbox is Linux).
- `flutter build apk` and a run on your phone (no Android SDK here).
- Real microphone and speaker use on Windows and Android.
- The new **App CI** workflow (`.github/workflows/client-ci.yml`) runs only
  after a push.

Steps: [apps/client/README.md](apps/client/README.md).

### Remaining (Phase 3b, deferred as agreed)
- Offline cache (SQLite) and outbox, sync endpoints on Core.
- Secure phone pairing with TLS certificate pinning (replaces plain HTTP
  on the LAN).

---

## Phase 2.2 — Local AI integration (2026-11-09)

Request: "ULTRON Local AI Integration — Phase 1" (Windows 11, Docker Desktop
+ WSL2, Ollama at `http://127.0.0.1:11434`, `qwen3.5:4b`; you verified
`POST /api/generate` → "ULTRON ONLINE"). Approved plan: option **A**
(backend only; no frontend yet).

### Audit (before changes)
| Area | Finding |
|---|---|
| Frontend | None in the repo; the Flutter app is Phase 3 (not started). |
| Backend | ULTRON Core, Python/FastAPI + PostgreSQL + Redis (Docker Compose or run directly). |
| API | REST `/api/v1` (auth, conversations, messages with SSE streaming, AI status/preferences). |
| AI | Provider system already had cloud (Groq, Gemini, OpenRouter, custom, Anthropic) and local (Ollama) side by side, cloud-first with local fallback, private → local only. |
| Gaps | `localhost` instead of `127.0.0.1` (Windows IPv6 issue); no guard against non-local Ollama addresses; no loading feedback while a model loads; no overall reply time limit; default model only in `.env.example`. |

### Changes
| Change | Details |
|---|---|
| Local-only guard | Ollama is used only at `127.0.0.1`, `localhost`, `::1`, `host.docker.internal` or the Compose `ollama` service. Other addresses are refused with a reason (status, readiness, `check-config`). A `cloud` backend never uses local AI. Opt-in for a secured remote Ollama: `ULTRON_OLLAMA_ALLOW_REMOTE=true` **and** `https`. |
| Defaults | `ULTRON_OLLAMA_MODEL` defaults to `qwen3.5:4b` in code; template/docs use `http://127.0.0.1:11434`; Docker keeps `host.docker.internal`. |
| Loading states | New SSE `status` events: `routing` → `waiting` / `loading_model` (from Ollama `/api/ps`) → `generating`. Existing events unchanged. |
| Keep-alive | `: keep-alive` SSE comments every `ULTRON_AI_STREAM_KEEPALIVE_SECONDS` (10) while waiting. |
| Time limit | `ULTRON_AI_MAX_REPLY_SECONDS` (300). Over the limit → code `timeout` (HTTP 504 when not streaming); partial text saved as `incomplete`. |
| Warm-up | `POST /api/v1/ai/local/warmup` loads the model (Ollama empty chat); `/ai/status` shows `model_loaded`. Rate-limited 6/min. |
| Tests | 25 new (`test_local_ai_integration.py`) + 2 live tests; streaming test updated for `status` events. |
| Windows script | Default `127.0.0.1`; new checks: warm-up, model loaded, loading-state events. |
| Docs | `WINDOWS_OLLAMA.md` (loading-state table for the app, new settings), `SECURITY.md` §3a, `ARCHITECTURE.md`, core README. |

No database schema changes; existing data and endpoints unchanged.

### Verified in this sandbox
| Check | Result |
|---|---|
| Lint + full suite | ✅ 162 passed, 11 live tests skipped (no `.env`, CI-style: 162 passed) |
| Real Ollama 0.40.15 runtime (no model) | ✅ `/api/ps` → `{"models":[]}` → `model_loaded = false`; warm-up of an unpulled model → real `404 … not found` → "not installed"; live suite 5 passed / 6 skipped (need the model) |
| Docker → host via `host.docker.internal` (stand-in Ollama with a 1.5 s "model load") | ✅ status `ready`, `model_loaded: false`; stream: `routing → loading_model → generating`, **3 keep-alives** during the load, 4 deltas, completed; warm-up → `already_loaded: true`; status → `model_loaded: true`; private conversation used local only |
| Guard | ✅ `192.168.x.x` / public hosts refused with reason; cloud backend refuses local addresses; https + opt-in accepted |

### Not done yet / remaining
1. **Real `qwen3.5:4b` replies through ULTRON have still not been observed.** The sandbox can't reach your PC or download models. Run the script below; it covers warm-up, chat, streaming with loading states, private, fallback and missing-model checks.
2. **No user-facing loading UI:** loading states exist in the API only; the app (Phase 3) will display them.
3. **`host.docker.internal` on real Docker Desktop + WSL2** is expected to work (it is Docker Desktop's documented host address) but was only exercised on Linux here; the script checks it on your PC.
4. The PowerShell script itself was not executed here (PowerShell can't be installed in this sandbox); its steps were mirrored with bash.
5. Cancellation and the one-reply-per-conversation lock are per server process (fine for the local backend).

### Windows commands

```powershell
docker compose up -d --build
powershell -ExecutionPolicy Bypass -File scripts\windows\Test-UltronOllama.ps1 -Email you@example.com
```

Existing `.env`: add the new lines from `docs/WINDOWS_OLLAMA.md` §3 first
(at least `ULTRON_OLLAMA_MODEL=qwen3.5:4b` and the `127.0.0.1` address).

---

## Phase 2.1 — Real Ollama integration (Windows, `qwen3.5:4b`)

Target: Ollama at `http://localhost:11434` on Windows, model `qwen3.5:4b`,
ULTRON Core (FastAPI) in Docker or run directly.

### Changes
| Area | Change |
|---|---|
| Model config | `.env.example`: `ULTRON_OLLAMA_MODEL=qwen3.5:4b`, `ULTRON_OLLAMA_BASE_URL=http://localhost:11434` (direct run), `ULTRON_CORE_OLLAMA_BASE_URL=http://host.docker.internal:11434` (Docker) |
| Thinking models | Qwen 3.5 can reason before answering. ULTRON now sends `think` explicitly (`ULTRON_OLLAMA_THINK`, default `false` for fast replies). Reasoning is never shown: the `thinking` field is ignored and inline `<think>…</think>` blocks are stripped. A reply that is only reasoning (output limit hit) is reported as an error instead of an empty answer. |
| Context size | Sends `num_ctx` (`ULTRON_OLLAMA_NUM_CTX`, default 8192). Ollama's own default is 4096 tokens (confirmed on Ollama 0.40.15), which would silently cut off history. |
| Model lifetime | Optional `ULTRON_OLLAMA_KEEP_ALIVE`. |
| Errors | Real Ollama `404 model '…' not found` → "not installed"; unsupported `think` → clear config error; out-of-memory → clear message. |
| Security | Ollama stays on `127.0.0.1`; Docker reaches it via `host.docker.internal`; docs say not to set `OLLAMA_HOST=0.0.0.0`; the Windows test checks Ollama isn't listening on the network. |
| Tests | 12 new adapter tests; new live suite `tests/test_ollama_live.py` (9 tests, `-m ollama_live`, skipped unless `ULTRON_TEST_OLLAMA_URL` is set). |
| Windows tooling | `scripts/windows/Test-UltronOllama.ps1` (end-to-end check, PowerShell 5.1 and 7), `docs/WINDOWS_OLLAMA.md` (exact commands, troubleshooting). |

### Actual results (2026-11-09)

This cloud session cannot reach your PC (no Remote Control folder is
shared), and the sandbox's network policy blocks downloading models from
`registry.ollama.ai`, so **`qwen3.5:4b` itself has not run yet**. What was
verified here:

| # | Task | Result here | Evidence |
|---|---|---|---|
| 1 | Verify Ollama provider | ✅ | Reviewed; 2 issues fixed (no `think` / no `num_ctx` sent). 37 adapter tests pass. |
| 2 | Model name `qwen3.5:4b` | ✅ | Tag matched exactly; `.env.example` and template test updated. |
| 3 | Ollama API connection | ✅ real runtime | Real **Ollama 0.40.15**: `/api/version`, `/api/tags`, `/api/chat` and `/api/show` responses checked; 4 live tests pass against it. |
| 3b | Docker → host connection | ✅ (sandbox) | Container reached a host service through `host.docker.internal`; readiness showed `local_ai: ok, model: qwen3.5:4b`. |
| 4 | Real chat through ULTRON | ✅ protocol / 🟡 real model | Full stack (HTTP → router → Ollama protocol) with a sandbox fake Ollama: JSON and streamed replies labelled `ollama` / `qwen3.5:4b` / local. Request sent to Ollama: `think: false`, `num_ctx: 8192`, no tools. |
| 5 | Response generation | 🟡 pending on PC | Needs the real model: run the script or live suite below. |
| 6 | Cloud → local fallback | ✅ (fake local) | Temporary backend with an unreachable cloud provider: `custom = offline → ollama = ok`, `fallback_used: true`. Same commands as the Windows script. |
| 7 | Private, local only | ✅ (fake local) | Private chat in `auto` mode: only `ollama` attempted. |
| 8 | Unavailable model | ✅ real runtime | Real Ollama returns `404 model 'qwen3.5:4b' not found` → ULTRON reports "not installed"; status `local_ai_available: false`; readiness `unavailable`; chat `no_ai_available`; private `private_requires_local_ai`. |

Test totals: **137 passed** (default suite) + live suite **4 passed /
5 skipped** against the real runtime (the 5 need the model). All 9 live
tests also pass against the sandbox fake, which confirms the test code
itself.

### To finish on Windows (exact commands)

From the repository folder in PowerShell, with Ollama running:

```powershell
docker compose up -d --build
powershell -ExecutionPolicy Bypass -File scripts\windows\Test-UltronOllama.ps1 -Email you@example.com
```

Optional developer suite (from `apps\core`):

```powershell
$env:ULTRON_TEST_OLLAMA_URL = "http://localhost:11434"
$env:ULTRON_TEST_OLLAMA_MODEL = "qwen3.5:4b"
uv run pytest -m ollama_live -v -s
```

Full guide: [docs/WINDOWS_OLLAMA.md](docs/WINDOWS_OLLAMA.md). Paste the
script's summary table back and this section will be updated with the real
model's results.

**Note:** the PowerShell script could not be executed here (PowerShell
can't be installed in this sandbox). Its steps were verified with an
equivalent bash run against the same Docker setup.

---

## Phase 2 — Intelligence Engine

### What was built

| Requirement | Implementation |
|---|---|
| **1. Cloud AI provider** | Provider-independent interface (`ai/providers/base.py`). Adapters: OpenAI-compatible HTTP for **Groq, Google Gemini, OpenRouter, custom** (free tiers), and **Anthropic Claude** via the official SDK (paid, optional; retries off for fast failover; server-side refusal fallback on). Keys only in `ULTRON_*` env vars (`SecretStr`). Streaming throughout. Errors mapped to: not configured, auth, rate limited, quota exhausted, unavailable, offline, invalid request, refused. |
| **2. Local AI provider** | Ollama adapter (`/api/chat` streaming, `/api/tags`). Configurable `ULTRON_OLLAMA_BASE_URL` + `ULTRON_OLLAMA_MODEL`. Available **only if the configured model is installed**; used for offline conversations. |
| **3. Provider router** | Cloud first (user-ordered), local fallback on failure / quota / rate limit / offline. Cooldowns in Redis. Modes `auto`, `cloud_only`, `local_only`. **Private → local only.** Every reply labelled provider, `cloud`/`local`, model, `fallback_used`, attempts. Never claims local AI that isn't installed. |
| **4. Chat system** | Conversations (create/list/read/rename/make private/delete), message history, context trimming per provider budget, JSON or **SSE streaming**, **cancellation** (endpoint + client disconnect), one reply at a time per conversation, clear error codes, partial replies kept as `incomplete`/`cancelled`. |
| **5. Security** | Keys never returned or logged; strict request validation (`extra="forbid"`, length, NUL bytes); chat rate limit; private conversations only on a local backend with a local DB and can't be made public; AI output is text only, never executed (no tools sent to models). See [docs/SECURITY.md](docs/SECURITY.md). |
| **6. Testing** | 76 new tests, all with fake providers or mocked HTTP: **no paid API usage**. |
| **7. Documentation** | Updated `PROJECT_STATUS.md`, `docs/ARCHITECTURE.md`; new `docs/DEVELOPMENT_ROADMAP.md`, `docs/SECURITY.md`, ADR-0007; dev guide, sync doc, READMEs, `.env.example`. |

New endpoints: `POST/GET /api/v1/conversations`, `GET/PATCH/DELETE
/api/v1/conversations/{id}`, `POST /api/v1/conversations/{id}/messages`,
`POST /api/v1/conversations/{id}/cancel`, `GET /api/v1/ai/status`,
`GET/PUT /api/v1/ai/preferences`. Migration `0002` adds `conversations`,
`messages`, `user_ai_preferences`.

### Test results (2026-11-09)

```
ruff check  → All checks passed
ruff format → 58 files already formatted
pytest      → 125 passed (67 unit, 58 integration) — 49 from Phase 1, 76 new
CI-style run (no .env, env-var URLs only) → 125 passed
```

GitHub Actions CI run #2 (commit `a2d71e1`): ✅ **success**: lint, 125
tests on fresh Postgres/Redis, and the Docker image built from the
committed Dockerfile.
<https://github.com/nityamsharma19022-ux/ultron-ai-assistant/actions/runs/42650362198>

Requested scenarios → tests:

| Scenario | Covered by |
|---|---|
| Cloud provider success | `test_cloud_provider_success`, `test_send_message_uses_cloud_and_stores_history`, `test_streaming_events`, real adapter parsing for OpenAI-compatible + Anthropic |
| Local provider success | `test_local_provider_success`, `test_local_only_preference`, `test_ollama_streams_ndjson` |
| Cloud failure → local fallback | `test_cloud_failure_falls_back_to_local` (+ cooldown), `test_cloud_failure_falls_back_to_local_via_api` |
| Missing API keys | `test_missing_api_keys_skip_cloud_without_calling_it`, `…_and_no_local_gives_clear_error`, `test_no_providers_configured`, adapter "not configured" tests, `.env.example` enables nothing |
| Quota exhaustion | `test_quota_exhaustion_moves_to_next_provider_and_cools_down`, `test_quota_exhausted_everywhere_uses_local`, `test_quota_exhaustion_via_api`, Groq/OpenAI/Gemini/OpenRouter/Anthropic quota mapping |
| Private conversation routing | `test_private_conversation_never_reaches_cloud`, `…_without_local_ai_fails_instead_of_using_cloud`, `test_private_ignores_cloud_only_preference`, API tests incl. private-by-default, can't switch off, refused on cloud backend |
| Offline behaviour | `test_offline_skips_remaining_cloud_providers_and_uses_local`, `test_offline_without_installed_local_model_does_not_claim_offline_ai`, `test_offline_with_local_model`, `test_offline_without_local_model` |
| Also | rate limits with `Retry-After`, mid-stream failure (no stitching), refusals not retried, user provider order, cancel + busy (409), validation (empty/blank/NUL/extra fields/too long), auth required, keys absent from status and OpenAPI, AI output stored as text only, stale replies marked failed |

### End-to-end checks in Docker (full stack)
- Migrations `0001 → 0002` applied on start.
- With nothing configured: chat returns `no_ai_available`; `/ai/status`
  lists every provider as `not_configured` with the reason.
- With the dev mock: streamed reply `message.created → provider.selected →
  delta ×8 → message.completed`, labelled `mock-cloud` / `cloud`, saved
  in history.
- Private conversation with no local AI: refused (`private_requires_local_ai`),
  cloud not used.
- **Real Ollama 0.40.15 runtime, no model installed:** `/ai/status` →
  `local model 'llama3.2' is not installed`; `local_ai_available: false`;
  readiness reports the same; `local_only` chat refused with that reason.
- Logs contain no message content.

### Bugs found and fixed during testing
1. **Provider order:** a preferred provider that also appeared in the
   default order lost its priority (later position overwrote it). Fixed:
   the user's order wins.
2. **Updating a conversation crashed (500):** the database-set
   `updated_at` was lazy-loaded outside async context. Fixed with
   `eager_defaults` on all timestamped models.
3. **Anthropic spend limit misclassified:** the SDK's spend-limit error is a
   subclass of its rate-limit error, so it got a 60 s cooldown instead of
   quota handling. Fixed by checking it first.
4. **Gemini per-minute limits** say "quota" in their message; treated as
   short rate limits (with Gemini's `retryDelay` hint) rather than 1-hour
   quota cooldowns.

### Limitations / notes
- **No real cloud provider was called** (by design: no paid usage, no keys
  in this environment). Adapters are tested against recorded-format mock
  responses; the first real call happens when you add a key.
- **No real local model reply** was tested here: the sandbox's network
  policy blocks `registry.ollama.ai`, so no model could be downloaded. The
  real Ollama runtime *was* tested for detection. On your PC:
  `ollama pull llama3.2`.
- Anthropic defaults to `claude-opus-5-5` (≈ $4 / $20 per million
  input/output tokens) with server-side refusal fallback
  (`fallbacks: "default"`) enabled. It's off unless you add a key. Set
  `ULTRON_ANTHROPIC_MODEL` to a cheaper model if preferred.
- Free-tier model names in `.env.example` (`llama-3.3-70b-versatile`,
  `gemini-2.5-flash`) are suggestions; check each provider's current list.
- Cancellation and the one-reply lock are per server process (fine for the
  single-process local backend; Redis-based for cloud hosting in Phase 5).
- The Docker image in this sandbox was again built from a copy of the
  Dockerfile that only adds the sandbox proxy CA to the build stage; the
  committed Dockerfile is unchanged and CI built it successfully.

---

## Phase 1 — Backend foundation (summary)

FastAPI app, `ULTRON_`-only configuration with separate local/cloud
databases and no automatic switching, health checks, async Postgres +
Redis, Alembic, owner/device auth (Argon2id, rotating refresh tokens),
structured logging, Docker image, CI. 49 tests; GitHub Actions run #1
passed (lint, tests, image build):
<https://github.com/nityamsharma19022-ux/ultron-ai-assistant/actions/runs/42622453068>

Fixed in Phase 1: private-domain owner emails couldn't log in; health
probes flooded INFO logs.

---

## Isolation check
No Supabase project created; no Netlify use; no access to other projects'
resources. All new settings are `ULTRON_`-prefixed.

## Next step
Review Phase 3 (screenshots and the Windows/Android steps in
`apps/client/README.md`), approve pushing the local commits, then decide on
Phase 3b.
