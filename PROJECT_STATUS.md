# ULTRON — Project status

_Last updated: 2026-11-09_

| Phase | Scope | Status |
|---|---|---|
| 0 | Architecture docs, Docker Compose (Postgres + Redis), env template | ✅ Done |
| 1 | ULTRON Core backend foundation | ✅ Done (CI green) |
| 2 | Intelligence Engine: AI provider router + chat API | ✅ Done (CI green) |
| 2.1 | Real Ollama integration (Windows, `qwen3.5:4b`) | 🟡 **Built and verified in sandbox; real-model run pending on your PC** |
| 3 | Flutter app (Android + Windows), pairing, offline cache/outbox, sync | ⏸ Not started (needs approval) |
| 4 | Memory (pgvector), voice, reminders | — |
| 5 | Optional ULTRON-only Supabase project, cloud hosting (not Netlify), edge role | — |

Full plan: [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md).

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
Phase 3 (Flutter app + sync) starts only after Phase 2 is reviewed and
approved.
