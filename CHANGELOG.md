# Changelog

All notable changes to ULTRON. Dates are when the work was committed to
`claude/fervent-lovelace-fqank5`.

## [Unreleased] — 2026-11-10 (round 2: "AI operating system")

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
