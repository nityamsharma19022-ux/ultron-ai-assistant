# ULTRON build status

Central progress file for the ULTRON master build directive (2026-11-10).
Updated after each stage with real results. "Verified" means run and seen
working; anything only possible on your PC or phone is listed separately
and is **not** claimed as done.

Environment: Claude Code cloud sandbox (Linux). It cannot reach your
Windows PC or your iQOO phone. It has the Flutter SDK, the official
Android SDK (added in this session), Docker (PostgreSQL + Redis), and no
Ollama.

## Overview

| Stage | Scope | Status |
|---|---|---|
| 0 | Audit and preservation | ✅ Done |
| 1 | Existing frontend/backend complete; Android build | ✅ APK builds; device install pending |
| 2 | Memory, context, tool registry | ✅ Backend done and tested |
| 3 | Task engine, permissions, agents protocol | ✅ Backend done and tested |
| 4 | Windows desktop agent | ✅ Built; E2E verified on Linux; Windows run pending |
| 5 | Android system assistant | ✅ Built, APK compiles; phone test pending |
| 6 | Files and multimodal | ✅ Documents (PDF, DOCX, XLSX, text); images/audio not yet |
| 7 | Pairing and secure transport | ✅ Pairing codes + HTTPS with pinned certificate |
| — | Control Center screens for the above | ✅ Tasks, Permissions, Activity, Memory, Agents, Assistant |
| 8 | QA, docs, release report | ✅ Done in the sandbox; device checks are yours (see below) |

| R2 | Round 2: autonomy levels, modes, proactive notifications, Command Center, search, projects, export, safety pause, new PC/web tools | ✅ Built and tested; see [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) |

**Release verdict:** built and tested as far as possible without your PC
and phone; **not yet a complete first release** until the device checks
in [ULTRON_RELEASE_CHECKLIST.md](ULTRON_RELEASE_CHECKLIST.md) pass.

Feature-by-feature status: [FEATURE_STATUS.md](FEATURE_STATUS.md);
roadmap: [ULTRON_ROADMAP.md](ULTRON_ROADMAP.md); limitations:
[KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## Stage 0 — Audit (2026-11-10)
- Branch `claude/fervent-lovelace-fqank5`, local = GitHub = `9e99a21`, clean
  working tree. `main` untouched.
- Existing: FastAPI Core (auth, chat, AI router, Ollama, SSE), Flutter app
  (chat, visualizer, dashboard, settings, voice). 162 backend + 74 app
  tests passing at start.

## Stage 1 — Android build
- Added a personal cloud environment `ultron-ai-assistant` that allows
  `dl.google.com`, `dl-ssl.google.com`, `download.flutter.io` (approved by
  the owner) and installed the official Android SDK (platform 36,
  build-tools 36.0.0, NDK 28.2).
- Sandbox-only Gradle setting: Maven Central rate-limited this machine
  (HTTP 429), so Gradle used Google's official Maven Central mirror. Not
  committed; your PC builds normally.
- **Result:** `flutter build apk --release` → `app-release.apk` (55.9 MB),
  package `dev.ultron.ultron_app`, label "ULTRON", target SDK 36,
  permissions INTERNET + RECORD_AUDIO. **Not installed on a phone yet.**

## Stage 2 — Memory and context
- `memories` table (PostgreSQL full-text search, `english` config),
  `activity_events` (audit log), `memory_enabled` preference. Migration
  `0003`.
- API: `GET/POST /api/v1/memories`, `PATCH/DELETE /memories/{id}`,
  `GET /memories/export`, `DELETE /memories?confirm=delete-all`,
  `GET /api/v1/activity`.
- Chat recalls pinned + relevant memories into the system prompt as
  background facts ("not instructions"). Private memories are recalled only
  in private (local-AI-only) conversations and never logged in activity.
- Tests: `tests/test_memory.py` (9).

## Stage 3 — Task engine
- Tool registry (`tasks/tools.py`): 22 tools across Core (memory, AI
  writing, reminders), PC (apps, files, workflows, status) and phone (apps,
  notifications, alarms, timers, status). Typed arguments, risk class A/B/C,
  permission scope, target.
- Planner: built-in rules for common commands (no AI needed), else the AI
  plans from the tool catalog; output is parsed and validated, unknown
  tools/arguments rejected, plans fixed before execution (prompt-injection
  boundary). Private requests plan with local AI only.
- Engine: queue in PostgreSQL, sequential steps, Core tools in-process,
  device steps claimed by agents (long poll), retries with backoff,
  verification (`verified: false` fails a step), device wait/stuck
  timeouts, pause/resume/cancel/retry, recurring tasks (hourly/daily/
  weekly), restart recovery.
- Permissions: class A runs without asking once its scope is granted
  (optional expiry); class B/C always ask; "always allow" never stored for
  B/C; master switch; emergency stop cancels everything and blocks new runs.
- Unified entry point `POST /api/v1/assistant/command` (text or voice):
  runs a task or answers a question; optional wait for the result.
- Migration `0004`. Tests: `tests/test_tasks.py` (19).

## Stage 4 — Windows desktop agent (`apps/agent`)
- Python program (`ultron-agent`): signs in as a Windows device, long-polls
  Core for PC steps, runs them, reports progress and results; reconnects
  with backoff; refresh token encrypted with Windows DPAPI.
- Local allow-lists in `.ultron-agent/agent.toml` (git-ignored): folders,
  apps (argument lists, no shell), workflows. Safe paths: no absolute
  paths, `..`, drive letters, UNC, device names or link escapes.
- Tools: status (psutil), apps list/open/focus (focus uses Win32 API),
  files list/search/read (text, MD, PDF, DOCX)/create folder/write (txt,
  md, docx, csv, json; atomic)/move/organize (by type or month, with undo
  journal and `ultron-agent undo`)/delete (Recycle Bin), workflows (time
  limit, cancel wins).
- `scripts/windows/Install-UltronAgent.ps1`: start at Windows sign-in
  (per-user Scheduled Task). **Not run yet** (no PowerShell here).
- **End-to-end run (real Core in Docker + real agent process, Linux):**
  "organize my downloads" asked first, then sorted 7 files into 6 folders;
  "open sleeper", "run the tests workflow", "how is my pc doing" ran without
  asking once granted; "open Notepad" refused (not an allowed app); a
  3-step task (AI writes a plan → agent saves `documents/Study/weekly-plan.md`
  → reads it back) completed; overwriting asked for approval.
- Tests: `apps/agent/tests` (29 + 1 Windows-only DPAPI test).
- CI: new **Agent CI** runs the agent tests on `windows-latest` and
  `ubuntu-latest`; **App CI** now also builds the release APK and the
  Windows app on GitHub's machines and keeps them as downloadable artifacts.

## Stage 5 — Android system assistant
- Native Kotlin (`apps/client/android`): `UltronVoiceInteractionService`,
  `UltronSessionService` + session (opens ULTRON's assistant screen via
  `startAssistantActivity`), `UltronRecognitionService` (required by
  Android; passes speech requests to the phone's own recognizer, the
  on-device one when offline is preferred; only used on Android 11 and
  older), `ACTION_ASSIST` / `VOICE_COMMAND` on the main activity, lock-screen
  launch flag (`supportsLaunchVoiceAssistFromKeyguard`).
- ULTRON does **not** take the assistant role itself: the System page links
  to Android's "Digital assistant app" setting and shows whether ULTRON
  holds the role (`RoleManager.isRoleHeld`).
- Phone tools over a method channel: status (battery, network), open apps
  by name (launcher query), alarms and timers through the clock app,
  notifications (asks for Android 13+ notification permission).
- Flutter: assistant screen (greets "Yes, I'm listening. What do you
  need?", listens, runs the command or answers, speaks the result, approve
  / always allow / no for tasks that need approval; "stop", "never mind",
  "go to sleep" close it). The phone acts as ULTRON's phone agent while the
  app is open; due reminders show as phone notifications and in the app.
- **Wake word:** not implemented. Android only lets system/privileged apps
  use always-on hotword detection (`AlwaysOnHotwordDetector` /
  `HotwordDetectionService` need system permissions); an ordinary app would
  have to keep the microphone open in a foreground service, which drains
  the battery and shows a permanent notification. The supported
  alternative is the system assistant gesture (long-press home / power,
  corner swipe, depending on the phone) once ULTRON is the default
  assistant. Not tested on the iQOO.
- **Result:** `flutter build apk --release` succeeds (57.2 MB); manifest
  contains the services and assist filters. **Not installed or tested on a
  phone** (no device or KVM emulator here).

## Control Center (Flutter)
- New sections: **Tasks** (command bar typed or spoken, task cards with
  steps/status, approve, always allow, reject, pause, resume, cancel,
  retry, repeat hourly/daily/weekly, STOP ALL emergency button;
  Permissions tab with master switch and per-scope toggles; Activity tab),
  **Memory** (search, add, edit, pin, private, delete, export as JSON,
  delete all, "use memories in chat").
- System page: Agents card (online devices, their apps/workflows) and
  Assistant card (default-assistant status, "Talk to ULTRON").
- Tests: +19 widget tests (93 total). They found and fixed four bugs: a
  disposed text field in the memory dialog, `ref` used in `dispose`, the
  phone agent starting during provider build, and timers left by the agent
  loop.

## Stage 6 — Files and documents
- Core: `POST /api/v1/documents` (multipart, 20 MB default limit),
  list, search, preview, delete. Text extraction for PDF (text layer),
  DOCX (with tables), XLSX (sheets as CSV), text/Markdown/CSV/JSON/code.
  Overlapping chunks with PostgreSQL full-text search. Same file uploaded
  again (SHA-256) is reused, not processed again. Migration `0005`.
- Chat: messages can carry `document_ids`; the relevant parts are given to
  the AI inside a `<<<DOCUMENTS … DOCUMENTS>>>` block with the rule that
  text inside documents is information, never instructions. Private
  documents only work in private (local-AI) conversations.
- Tasks: `docs.search` and `docs.read` tools; e.g. read a document and
  have `ai.write` summarise it (the source goes in a data block too).
- App: Memory section now has a **Documents** tab (upload, private flag,
  list, "Ask about it", delete); paperclip in the chat box to attach
  documents; attachments shown as chips and kept for follow-up questions.
- **Not supported yet (said in the app and the API):** images and scanned
  PDFs (no OCR/vision model), audio files (no server transcription; speech
  is turned into text on the device). Embedding/vector search (pgvector)
  is not used yet; search is PostgreSQL full-text.
- Tests: backend `tests/test_documents.py` (8, with real generated PDF,
  DOCX and XLSX files); app `test/features/documents_test.dart` (3).

## Stage 7 — Pairing and secure transport
- **Pairing codes:** a signed-in device (System → Devices → Pair a device)
  creates an 8-character code (single use, 10 minutes, stored only as a
  hash in Redis, redemption rate-limited 10 per 10 minutes per address).
  The phone ("Pair with a code instead" on the sign-in screen) or the
  Windows agent (`ultron-agent pair`) uses it instead of the password and
  gets its own revocable device sign-in.
- **HTTPS on the LAN:** `ultron-core tls-init --host <PC's LAN IP>` makes a
  self-signed certificate (EC P-256) in the git-ignored `.ultron-core/tls`;
  Core serves HTTPS when `ULTRON_TLS_CERT_FILE`/`ULTRON_TLS_KEY_FILE` are
  set (Compose mounts the folder). The phone pins the certificate's
  SHA-256 after you check its short form against the PC's dialog (the
  pairing code is only sent after that), refuses a certificate that
  differs from what Core reports, and from then on trusts only that
  certificate. The agent trusts it via `[server] ca_file`.
- **Real check (this sandbox):** generated a certificate, ran Core with
  HTTPS: pinned client connected, unpinned client refused ("self-signed
  certificate"), plain HTTP refused, on-the-wire fingerprint = reported
  fingerprint, container health check works over HTTPS; the real agent
  paired with a code over HTTPS and polled for work; reusing the code was
  refused; without `ca_file` the agent stops with a clear message.
- Tests: backend `test_pairing.py` (4), app `pairing_test.py` (7), agent
  (+2).
- **Not done:** QR-code pairing (needs a camera scanner); the phone has to
  be on the same network as the PC (no relay/cloud reachability yet).

## Bugs found by the end-to-end run and fixed
- **Agent long poll returned HTTP 500** when there was no work and it
  waited more than one round (expired ORM objects lazy-loading in async).
  Seen in the real agent's log; reproduced in a new test
  (`test_long_poll_waits_then_returns_no_work`); fixed by keeping plain IDs
  and replacing `expire_all()` with targeted refreshes.

## Stage 8 — QA, documentation, release report
- Full suites: backend 203 passed / 11 skipped (live Ollama), app 103
  passed, agent 31 passed (+1 Windows-only). `ruff` (incl. security rules)
  and `flutter analyze` clean.
- CI on GitHub: Core CI, Agent CI (**windows-latest** and ubuntu), App CI
  (tests, **release APK**, **Windows release build** on windows-latest),
  all green on the last pushes; APK and Windows build kept as artifacts.
- Security: `pip-audit` (Core, agent) no known vulnerabilities; secret
  scan of tracked files clean; see [ULTRON_SECURITY.md](ULTRON_SECURITY.md).
- End-to-end in the sandbox: real Core (Docker) + real agent process +
  web build of the app in Chromium; screenshots of Tasks, Permissions,
  Activity, Memory, Documents, System (agents, assistant), pairing dialog,
  phone layout and the assistant screen.
- Fixed in this stage: a misleading "Could not read the reply aloud"
  message when no voice is available (now says speech isn't available).
- Docs: [ULTRON_ARCHITECTURE](ULTRON_ARCHITECTURE.md),
  [ULTRON_SETUP_GUIDE](ULTRON_SETUP_GUIDE.md),
  [ULTRON_ANDROID_GUIDE](ULTRON_ANDROID_GUIDE.md),
  [ULTRON_WINDOWS_GUIDE](ULTRON_WINDOWS_GUIDE.md),
  [ULTRON_SECURITY](ULTRON_SECURITY.md),
  [ULTRON_RELEASE_CHECKLIST](ULTRON_RELEASE_CHECKLIST.md).

## Test results (latest run, 2026-11-10)
- Backend: **228 passed** (+11 live-Ollama tests not run here), ruff clean.
- App: **117 passed**, `flutter analyze` clean, release APK (58.7 MB) and
  web build.
- FreeLLMAPI: real Core server ↔ stand-in gateway on 127.0.0.1:31415 PASS.
- Agent: **36 passed** (+1 Windows-only DPAPI test, runs in CI on Windows).
- Live check: Core rebuilt in Docker at migration `0007`; the web build
  in Chromium (1600 px desktop, 412 px phone) showed the Command Center
  with live metrics and real proactive notifications.

## Known bugs
- None open. Limitations: [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## Device-only verification still required
- iQOO: install the APK, pair over HTTPS, choose ULTRON as the digital
  assistant, invoke it, phone tools (alarm, open app, notification), voice.
- Windows PC: run the app (`flutter run -d windows` or the CI build), run
  the agent and its checklist, start-at-sign-in script.
- Real cloud AI call with your free key; real Ollama (`qwen3.5:4b`).
- Full lists: [Windows](ULTRON_WINDOWS_GUIDE.md#4-verification-checklist-on-your-pc),
  [Android](ULTRON_ANDROID_GUIDE.md#7-verification-checklist-on-the-iqoo).
