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
| 5 | Android system assistant | ⏳ |
| 6 | Files and multimodal | ⏳ |
| 7 | Pairing and secure transport | ⏳ |
| — | Control Center screens for the above | ⏳ |
| 8 | QA, docs, release report | ⏳ |

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

## Test results (latest run, 2026-11-10)
- Backend: **190 passed, 11 skipped** (live Ollama tests), ruff clean.
- App: 74 passed (unchanged since Phase 3; new screens come later).
- Agent: 29 passed (+1 Windows-only, runs in CI).

## Known bugs
- None open.

## Device-only verification still required
- Install the APK on the iQOO phone; sign in; chat.
- Windows build of the app (needs Visual Studio C++ workload).
- Real Ollama run (`qwen3.5:4b`) on the PC.
