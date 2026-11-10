# ULTRON security

How ULTRON protects credentials, conversations and devices. Covers what is
built today (Phases 1–3) and the rules later phases must follow.

## 1. Threat model (personal assistant)

| Asset | Main risks | Main controls |
|---|---|---|
| AI provider API keys | Leaking to the app, logs, git or another project | Server-side only, `SecretStr`, never returned or logged, `.env` git-ignored |
| Conversations | Sent to a cloud AI or stored in the cloud against the user's wishes | Private conversations: local AI only, local storage only |
| The user's devices | AI output (or a prompt injection) triggering actions | AI output is text only; the backend has no code path that executes it |
| The account | Password guessing, stolen tokens, lost devices | Argon2id, rate limits, rotating refresh tokens with reuse detection, device revocation |
| Other projects | Accidental reuse of their database, keys or deployments | `ULTRON_`-only config, separate DB/Redis/volumes, no Netlify ([ADR-0004](adr/0004-project-isolation.md)) |

## 2. Credentials and API keys

- All keys live in the server's `.env` (git-ignored) or environment, with
  `ULTRON_` prefixes. Only `.env.example` (placeholders) is committed.
- Settings hold keys as `SecretStr`: they are masked in `repr`, config dumps
  and `ultron-core check-config`.
- **Keys never reach the frontend.** The Flutter app talks only to ULTRON
  Core; Core talks to AI providers. `GET /api/v1/ai/status` reports *whether*
  a provider is configured, never the key (covered by tests).
- Provider error messages are rewritten into ULTRON's own categories;
  upstream response bodies are not passed to clients.
- Keys travel in headers (`Authorization`), never in URLs, and HTTP-client
  request logging is turned down so URLs are not logged either.
- Tests force all API keys empty, so the test suite can never make a paid
  call even if a developer's `.env` has real keys.
- `ULTRON_AI_DEV_MOCK` (fake provider for development) is refused when
  `ULTRON_ENV=production`.

## 3. Private conversations stay local

A conversation marked **private**:
1. is routed **only to local AI** (Ollama). The router drops cloud providers
   before trying anything, and has a second check per provider. If no local
   model is available, the request fails with
   `private_requires_local_ai`; it never falls back to the cloud;
2. can only be created on a **local backend using a local database**
   (`ULTRON_DEPLOYMENT=local` and `ULTRON_DB_MODE=local`); a cloud backend
   refuses with HTTP 409;
3. **cannot be made non-private** later (the API only accepts
   `is_private: true`);
4. will be **excluded from cloud sync** (rule for Phase 3/5 sync, see
   [SYNC.md](SYNC.md)).

Users can make every new conversation private by default
(`private_by_default` preference).

## 3a. Local AI stays local

- Ollama has no authentication, so ULTRON Core only connects to it on the
  same machine: `127.0.0.1`, `localhost`, `::1`, `host.docker.internal` or
  the Compose `ollama` service. Any other address is refused and reported
  ("not on this machine") in status, readiness and `check-config`.
- A backend with `ULTRON_DEPLOYMENT=cloud` never uses local AI, so a
  deployed server can't silently try to reach an Ollama it can't secure.
- The only exception is deliberate: `ULTRON_OLLAMA_ALLOW_REMOTE=true` **and**
  an `https` address (e.g. a remote Ollama behind an authenticating TLS
  proxy). Plain `http` to another host is always refused.
- Apps never talk to Ollama; they only talk to ULTRON Core. Ollama stays on
  its default `127.0.0.1:11434`; never set `OLLAMA_HOST=0.0.0.0`.

## 3b. Voice in private conversations

The app uses the device's own speech engines; ULTRON Core never receives
audio.

- **Voice input** in a private conversation is allowed only where speech
  recognition is known to run on the device: Windows Speech (SAPI
  dictation) on Windows. On Android the system recogniser usually uses
  Google's online service, and the plugin's "on-device" option falls back
  to it silently, so voice input is **off** in private conversations there
  (the mic explains why). If a chat is switched to private while listening,
  the words are discarded, not sent.
- **Read-aloud** of a private reply uses only an offline voice (Android
  voices report whether they need the network; Windows voices are local).
  If there is none, the reply is not read and the app says so.
- Standard conversations may use the platform's online recogniser; the
  Settings → Voice page says which applies on the device.

## 4. AI output is never executed

- Providers receive text and return text. ULTRON never sends tool or
  function definitions to a model, so a model cannot request an action.
- The backend stores and returns AI output as data. No code path parses
  it as a command, URL to open, shell input or device instruction (a test
  checks that command-shaped output is returned verbatim and nothing else
  happens).
- The system prompt tells the model it cannot take actions, so it explains
  steps instead of pretending to do them.
- **Rule for future phases:** any device action (reminders, opening apps,
  etc.) must go through an explicit, allow-listed action framework with
  user confirmation on the device. It must never execute model output
  directly. This needs its own security review before it is built.

## 5. Request validation and limits

- All request bodies are Pydantic models with `extra="forbid"`; unknown
  fields are rejected (422).
- Chat messages: 1 to `ULTRON_CHAT_MAX_MESSAGE_CHARS` (default 12,000)
  characters, trimmed, must not be blank, no NUL bytes.
- Path IDs are UUIDs; conversations belong to their owner (others → 404).
- Rate limits (Redis, per window):
  - login: per IP and per email (`ULTRON_LOGIN_RATE_LIMIT_*`) → 429;
  - chat: per user per minute (`ULTRON_CHAT_RATE_LIMIT_PER_MINUTE`, default 20) → 429.
- One reply at a time per conversation (409 while one is running).
- Provider calls have connect/read timeouts, and each reply has a hard time
  limit (`ULTRON_AI_MAX_REPLY_SECONDS`, default 300); a failing provider is
  put on a cooldown so it isn't hammered.
- Local model warm-up is rate-limited (6 per minute per user).
- If Redis is down, rate limiters fail **open** (logged) so the owner is not
  locked out of a local fallback backend.

## 6. Authentication (Phase 1)

See [ADR-0006](adr/0006-authentication.md): single owner created from the
CLI, Argon2id, 15-minute access tokens bound to a device, rotating refresh
tokens with family revocation on reuse, instant device revocation.

## 7. Logging

- Structured logs with request IDs.
- **Message content is never logged**, only status, provider, error code
  and character count.
- Keys named `password`, `token`, `authorization`, … are redacted by a
  logging processor.

## 8. Network exposure

- PostgreSQL and Redis bind to `127.0.0.1` only.
- The API binds to `127.0.0.1` by default; LAN access for the Android app is
  an explicit opt-in (`ULTRON_CORE_BIND_HOST`), and pairing with TLS
  certificate pinning is planned for Phase 3b.
- The Android app allows plain HTTP (`usesCleartextTraffic`) so it can reach
  ULTRON Core on the emulator host or the PC's LAN address until pairing.
- The app stores login tokens in the OS secret store (Windows Credential
  Manager, Android Keystore); only non-secret preferences go in ordinary
  app storage.
- The Docker image runs as a non-root user.

## 9. Known gaps (tracked)

| Gap | Plan |
|---|---|
| LAN traffic between Android and the Windows backend is plain HTTP when enabled | Phase 3b: TLS + certificate pinning at pairing |
| Cancellation and the "one reply at a time" lock work within one server process | Fine for the local backend (single process); use Redis for multi-process cloud hosting (Phase 5) |
| No audit of prompt-injection content inside conversations | Low risk while AI output can't trigger actions; revisit with the action framework |
| `.env` holds secrets in plain text on the PC | Acceptable for a personal machine; an OS secret store can be evaluated later |

## 10. Reporting

This is a personal project. If you find a problem, open a private issue or
contact the repository owner directly. Never post keys in issues.
