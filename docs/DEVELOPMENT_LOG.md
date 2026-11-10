# ULTRON development log

Newest first. Each entry: what was done, how it was checked, what's left.

## 2026-11-10 — First run on the owner's Windows PC

Done by the owner, step by step, with photos (not in the sandbox):
- FreeLLMAPI on 127.0.0.1:31415 lists working models (Gemini, Qwen
  3.8 27B, gpt-oss and others).
- `docker compose up -d --build`: `/health/ready` → ready, database at
  0007, Redis ok, **local AI ok (`qwen3.5:4b`)**.
- Windows app (CI build) signs in; Home shows Core online, CLOUD and LOCAL.
- Windows agent: installed with `uv sync`, signed in, connected with 19
  tools; Home → Devices shows live CPU, memory, battery, disk.

Bugs found there and fixed:
- "open files" failed ("'files' isn't in your allowed apps"): the planner
  now understands everyday app names (files → File Explorer, browser →
  Chrome, vscode → VS Code) and leaves unknown apps to the AI planner
  instead of sending a step that can only fail.
- Home → AI activity never refreshed: now every 20 s and when a task
  changes.
- The owner's Downloads folder is `E:\Downloads`, not the default; fixed in
  their `agent.toml`.

## 2026-11-10 — Round 3: FreeLLMAPI and project audit

Owner request: "Master development, integration & completion directive"
(FreeLLMAPI gateway at `http://127.0.0.1:31415`).

- **Mission 1 (audit):** [ULTRON_STATUS_REPORT.md](ULTRON_STATUS_REPORT.md).
- **Mission 2 (GitHub):** branch clean and in sync with GitHub; CI green;
  `main` untouched.
- **Mission 3 (backend):** Docker services restarted and healthy; database
  at revision 0007.
- **Mission 4 (AI core):** FreeLLMAPI provider (cloud, never for private
  chats), `/v1` added automatically, `X-Routed-Via` model recorded, token
  counts requested; provider test endpoint and usage endpoint; Test button
  and usage card in the app.
- **Checks:** backend 228 PASS, app 117 PASS, agent 36 PASS. End to end:
  a real Core server chatted through a stand-in gateway on
  127.0.0.1:31415 (status ready, test OK, streamed reply, routed model and
  tokens recorded); a private chat was refused and the gateway never
  received it.
- **Not verified:** your real FreeLLMAPI install (port and key), because
  this sandbox can't reach your PC.

## 2026-11-10 — Round 2: toward an AI operating system

Owner request: the "ULTRON ultimate master prompt" (autonomous
development; AI brain, memory, companions, proactive AI, command center,
security). Security limits stay in force: important actions need
approval, no covert monitoring, credentials stay out of the code.

**R2-1 Autonomy levels and operating modes** (commit `c7bf9ed`)
- Levels 0–5 per area mapped onto the existing permission engine. Level 0
  hides that area's tools from the planner; level 5 allows plans up to 20
  steps. Class B/C and always-ask scopes still ask.
- Modes change the system prompt, routing, memory use, allowed areas and
  quiet notifications. Migration `0006`.

**R2-2 Notifications, proactive engine, device metrics** (`c7bf9ed`)
- Deduplicated notifications; proactive rules run every 30 s in the task
  engine. Metrics stored in Redis for 3 minutes.

**R2-3 New PC and web tools, task-type routing** (`c7bf9ed`)
- Agent tools: copy, rename, running programs, close app (always asks;
  never touches the agent or its parents; apps started with arguments are
  matched by their full command line), open link, Windows toast.
- `web.read`: every host and redirect resolved and refused if not a public
  address (incl. IPv4-mapped loopback and cloud metadata addresses).

**R2-4 Search, projects, memory pause, export, safety pause** (`9b5dad7`)
- Migration `0007`: message search index, project columns, memory pause.

**R2-5 Command Center UI** (`e341006`)
- Home screen with widgets and floating panels; bell; modes, quiet hours,
  daily briefing, background styles, export in Settings; conversation
  search; memory projects; phone metrics.
- Tests found real layout overflows (phone top bar, sidebar, autonomy
  rows); fixed before commit.

**Planner rules added** for "close <app>" (always asks) and "open
<web address>", so these work without any AI.

**CI found two issues, fixed:** on Windows, closing an app started from a
Python venv closes the launcher and its child (test assumed one process);
and the agent skipped its first metrics push on a machine booted less
than 30 seconds earlier.

**Checks**
- Backend: **221 passed** with real PostgreSQL + Redis; ruff clean.
- Agent: **36 passed** on Linux (+1 Windows-only; Windows CI on push).
- App: `flutter analyze` clean; **116 passed**.
- Live run: Core rebuilt in Docker (migration `0007` applied); the web
  build was used in Chromium at desktop and phone sizes. The live
  proactive engine produced real notifications (approvals waiting, low
  phone battery from pushed metrics, daily briefing) that showed up in the
  bell and Command Center.
- Release APK builds (58.7 MB). Not installed on a phone.

**Not done / next:** semantic memory, sync, external integrations,
keyboard/mouse automation, wake word on Windows, custom background image,
scoped agent tokens. Device checks on your PC and phone.

## 2026-11-10 — Round 1: master build (stages 0–8)
Memory, documents, task engine, Windows agent, Android assistant, pairing
and HTTPS. Details and results:
[ULTRON_BUILD_STATUS.md](ULTRON_BUILD_STATUS.md).

## Earlier phases
Core backend, AI router, chat API, Flutter app. See
[../PROJECT_STATUS.md](../PROJECT_STATUS.md).
