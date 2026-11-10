# ULTRON architecture

ULTRON is one assistant with four parts that share one account, one
conversation history, one memory, one task engine and one set of
permissions.

```
            ┌──────────────────────── ULTRON Core (apps/core) ─────────────────────────┐
            │ FastAPI · PostgreSQL · Redis                                              │
            │                                                                           │
 phone /    │  auth & devices ─ pairing ─ chat (SSE) ─ AI router (cloud → local Ollama) │
 PC apps ──►│  memory ─ documents ─ assistant/command ─ planner ─ task engine           │
 (HTTPS on  │  permissions ─ activity log ─ reminders ─ schedules ─ agent protocol      │
  the LAN)  └───────────▲───────────────────────────────▲───────────────────────────────┘
                        │ long poll: claim step,         │ long poll
                        │ report result                  │
          ┌─────────────┴────────────┐       ┌───────────┴─────────────────────────────┐
          │ Windows agent (apps/agent)│       │ ULTRON app (apps/client, Flutter)      │
          │ files · apps · workflows  │       │ Control Center on Windows and Android, │
          │ status; local allow-lists │       │ phone agent, Android system assistant  │
          └──────────────────────────┘       └─────────────────────────────────────────┘
```

## A. ULTRON Core (`apps/core`)

| Module | What it does |
|---|---|
| `auth/` | Owner account (Argon2id), per-device JWT access tokens, rotating refresh tokens with reuse detection, device revocation |
| `pairing.py` | One-time pairing codes; HTTPS info (certificate fingerprint) |
| `tls.py` | Self-signed LAN certificate (`ultron-core tls-init`) |
| `ai/` | Provider adapters (Groq, Gemini, OpenRouter, custom OpenAI-compatible, Anthropic, Ollama, dev mock) behind one interface; router: cloud first in the user's order, local fallback, private → local only, cooldowns |
| `chat/` | Conversations, streaming replies (SSE), cancel, context trimming; adds recalled memories and document excerpts to the system prompt |
| `memory/` | User-controlled long-term memory, full-text search, recall |
| `documents/` | Upload, text extraction (PDF, DOCX, XLSX, text), chunks, search |
| `tasks/` | Tool registry, planner, permissions, engine, agent protocol, reminders, schedules, `POST /assistant/command` |
| `activity.py` | Audit log shown to the user |
| `modes.py` | Operating modes (built-in + custom): prompt, routing, memory use, allowed areas, quiet |
| `notifications.py` | Notifications (priority, dedupe, quiet hours), notification settings, device metrics (Redis, 3 min) |
| `proactive.py` | Proactive rules run by the task engine every 30 s (failed tasks, approvals, reminders, offline devices, low battery, paused tasks, daily briefing) |
| `safety.py` | Automatic safety pause (failure burst, task flood) |
| `web.py` | `web.read`: public web pages only, every redirect re-checked |
| `ai/profiles.py` | Routing by task type (`ULTRON_AI_TASK_PROFILES`) |
| `backup.py` | JSON export of a user's data (`GET /export`, `ultron-core export`) |

Database tables (Alembic migrations `0001`–`0007`): users, devices,
refresh_tokens, conversations, messages, user_ai_preferences, memories,
activity_events, tasks, task_steps, permission_grants, automation_state,
agents, reminders, schedules, documents, document_chunks,
assistant_modes, notifications, notification_settings.

### Model adapters
Every provider implements `ChatProvider` (`ai/providers/base.py`):
`is_configured`, `availability`, `stream(ChatRequest)`. Adding a model or
provider means adding one adapter and registering it in `ai/registry.py`;
nothing else changes. Requests are text in, text out: **no tool
definitions are sent to models**.

### How a command becomes actions
1. **Entry**: `POST /api/v1/assistant/command` (Tasks command bar, the
   assistant screen, the phone assistant).
2. **Plan**: built-in rules first (open/switch app, organize a folder,
   remember, remind, run workflow, status), otherwise the AI planner. It
   sees the tool catalog and the names of your folders, apps and
   workflows. Its answer is parsed as JSON; every tool must exist and every
   argument is validated (`tasks/tools.py`). Questions get an answer
   instead of a task.
3. **Permission check** per step (`tasks/permissions.py`): B and C and
   always-ask scopes (delete, close app) always ask; class A depends on the
   area's **autonomy level**: 0 answer only (tools hidden), 1 always ask,
   2 read-only runs, 3 granted scopes run (default), 4 all class A runs,
   5 like 4 with plans up to 20 steps. Master switch, emergency stop and
   the automatic safety pause block everything.
4. **Execution** (`tasks/engine.py`): Core tools run in Core; PC and phone
   steps wait for that device's agent, which claims them by long poll and
   reports the result. Results can be passed to later steps
   (`content_from_step`, `source_step`), always as data.
5. **Recovery and verification**: retryable errors are retried with
   backoff; a result with `verified: false` fails the step; devices that
   don't connect or stop responding time out.
6. **Report**: task summary, short spoken message ("Done. Opened VS
   Code."), activity log entries.

## B. Android system assistant (`apps/client/android`)
`UltronVoiceInteractionService` + `UltronSessionService` make ULTRON
selectable as the phone's digital assistant (the user chooses it in
system settings). Invoking the assistant opens the app's assistant screen
(`AssistantScreen`): greeting, listen, command, spoken result, approvals.
`UltronRecognitionService` forwards speech to the phone's own recognizer
(required by Android 11 and older). The phone runs `phone.*` steps
(apps, alarms, timers, notifications, status) while ULTRON is open.

## C. Windows desktop agent (`apps/agent`)
A Python background program. Signs in as a Windows device (password or
pairing code), announces its tools and the *names* of its allowed
folders, apps and workflows, then long-polls Core. Every file path must be
inside an allowed folder; apps and workflows are fixed argument lists from
its own config (no shell). See `docs/ULTRON_WINDOWS_GUIDE.md`.

## D. Control Center (`apps/client`)
Flutter app for Windows and Android: **Home** (Command Center: clock,
mode, command bar, quick commands, live panels for devices, tasks,
reminders, notifications, AI activity and autonomy; floating draggable
panels on desktop), chat with streaming and conversation search, animated
AI visualizer, Tasks (command bar, approvals, controls, STOP ALL,
permissions, activity), Memory (memories with projects, documents),
System (Core, AI sources, local model, agents, assistant, devices,
pairing), Settings (AI routing, operating mode, notifications,
appearance, voice, data export, account). A notification bell is always
visible.

## Data flow and privacy
- Apps talk only to ULTRON Core; Core talks to AI providers. Keys stay in
  Core's `.env`.
- Private conversations, memories and documents are used with local AI
  only, and only by a local backend.
- Untrusted text (documents, files, web-like content) is passed to models
  inside marked data blocks and is never used to choose actions; plans are
  fixed before any step runs.

## Tests
- Core: `apps/core/tests` (pytest, real PostgreSQL/Redis, fake AI
  providers).
- Agent: `apps/agent/tests` (also run on Windows in CI).
- App: `apps/client/test` (widget tests with a fake Core, fake speech and
  fake platform channels).
- CI: Core CI, Agent CI (Windows + Linux), App CI (tests, release APK,
  Windows build).
