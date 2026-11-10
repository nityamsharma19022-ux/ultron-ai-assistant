# Changelog

All notable changes to ULTRON. Dates are when the work was committed to
`claude/fervent-lovelace-fqank5`.

## [Unreleased] — 2026-11-10 (Phase 1: voice)

### Fixed
- **Windows voice got stuck on "listening".** Root cause: the
  `speech_to_text` plugin's Windows recogniser (old Windows Speech/SAPI)
  never reports a final result or "done" and doesn't support English
  (India) or Hindi, and ULTRON had no time limit. Windows now records audio
  in the app and ULTRON Core transcribes it; a watchdog ends listening in
  every case.

### Added
- `POST /api/v1/voice/transcribe`, `/voice/status`, `/voice/warmup`:
  faster-whisper `small` on the CPU (English + Hindi), audio never
  stored. Model cached in the `ultron_models` Docker volume.
- Settings → Voice: speech engine status and **Prepare voice**.
- Push-to-talk feedback: listening state and a sound immediately;
  "Transcribing…"; haptic tick on Android.
- Replies are read aloud **sentence by sentence while they stream**.

## [Unreleased] — 2026-11-10 (ULTRON 2.0, part 1)

### Added
- **12-hour time everywhere** (9:30 PM) by default: Home clock, reminders,
  activity, permissions, quiet hours, daily briefing, time picker,
  reminder confirmations, alarm steps and AI answers. Optional 24-hour in
  Settings → Personality & speed, synced across devices.
- **Personality**: humble, warm, polite and professional. ULTRON
  addresses you as "Sir" (changeable or off) and replies like "Certainly,
  Sir. Reminder set for today at 9:30 PM."
- **Response modes**: Instant (fast model, short answers), Balanced, Deep
  reasoning; per user or per message. FreeLLMAPI uses `auto:fast` /
  `auto:smart`.
- **Measured speed**: time to first word and total time for every reply,
  shown under replies and as averages on System → AI usage.
- The AI knows your local date and time.
- Reports: ULTRON_UPGRADE_AUDIT, AI_BRAIN_REPORT, PERFORMANCE_REPORT,
  VOICE_SYSTEM_REPORT.
- Migration `0008`.

### Fixed (found on the owner's PC)
- "open files" now opens File Explorer (everyday app names understood).
- Home → AI activity refreshes by itself.

## 2026-11-10 (round 3: FreeLLMAPI)

### Added
- **FreeLLMAPI** gateway as the first cloud AI source
  (`ULTRON_FREELLMAPI_*`; Docker reaches it at `host.docker.internal`).
  Counts as cloud, so private conversations never use it. The real
  upstream model (`X-Routed-Via`) and token counts are recorded.
- **Test an AI provider through Core** (`POST /ai/providers/{name}/test`,
  System → AI sources → Test).
- **AI usage** per source and model (`GET /ai/usage`, System → AI usage).
- Docs: [FREELLMAPI.md](docs/FREELLMAPI.md),
  [ULTRON_STATUS_REPORT.md](docs/ULTRON_STATUS_REPORT.md).

## 2026-11-10 (round 2: "AI operating system")

### Added
- **Command Center** home screen: clock, active mode, command bar, quick
  commands, live panels for devices (CPU/RAM/disk/battery/network), tasks,
  reminders, notifications, AI activity and autonomy. Desktop can switch
  to floating, draggable panels.
- **Autonomy levels 0–5** per area (Core, PC, phone). Important or
  irreversible actions still ask at every level.
- **Operating modes**: Normal, Work, Developer, Study, Focus and your own.
  A mode changes ULTRON's tone, preferred AI, memory use, what it may act
  on and whether it stays quiet.
- **Notifications and proactive alerts**: bell with unread count, pop-ups
  for important ones, quiet hours, minimum priority, daily briefing;
  alerts for failed tasks, waiting approvals, due reminders, offline
  devices, low battery, long-paused tasks.
- **Automatic safety pause**: automation turns itself off after a burst of
  failures or a flood of new tasks, with an urgent notification.
- **Conversation search** across all chats, with highlighted matches.
- **Project memories** and **pause memory saving**.
- **Export all data** (`GET /api/v1/export`, `ultron-core export`,
  Settings → Your data).
- **Routing by task type** (`ULTRON_AI_TASK_PROFILES`, e.g.
  `coding=groq;reasoning=anthropic`).
- **Web page reading** for tasks (`web.read`), refusing private and local
  network addresses.
- Windows agent: copy, rename, list running programs, close an allowed
  app, open web links, Windows toast notifications, live metrics.
- Phone: battery and network sent to the Command Center every minute.
- App: background styles (grid, aurora, stars, plain) and theme presets.
- Database migrations `0006` (modes, notifications, levels) and `0007`
  (projects, memory pause, message search index).

### Changed
- The app opens on **Home** (Command Center) instead of Chat.

## 2026-11-10 (round 1: master build)
Memory, documents, task engine with permissions, Windows agent, Android
system assistant, pairing and HTTPS. See
[docs/ULTRON_BUILD_STATUS.md](docs/ULTRON_BUILD_STATUS.md).

## Earlier
Core backend, AI router, chat, Flutter app (chat, visualizer, dashboard,
settings, voice). See [PROJECT_STATUS.md](PROJECT_STATUS.md).
