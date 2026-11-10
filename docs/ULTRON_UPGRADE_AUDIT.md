# ULTRON 2.0 upgrade audit

Audit for the "ULTRON 2.0 ultimate master upgrade" request (2026-11-10):
what exists, what the request adds, what was done in this round, and what
is left. Feature-by-feature status: [FEATURE_STATUS.md](FEATURE_STATUS.md).

## Starting point (verified on the owner's PC the same day)
- ULTRON Core in Docker: ready, database migrations current, Redis ok,
  local AI (Ollama `qwen3.5:4b`) ok.
- FreeLLMAPI gateway on `127.0.0.1:31415` with working models.
- Windows app (CI build): sign-in, Command Center, Core online,
  CLOUD + LOCAL.
- Windows agent: connected with 19 tools; live CPU, memory, battery and
  disk on Home.
- Bugs found there were fixed: "open files", AI activity not refreshing.

## Gaps against the request, and what this round did
| Request area | Before | This round |
|---|---|---|
| 12-hour time everywhere | Mixed: 24-hour clock, ISO timestamps in some messages | **Done.** 12-hour default in the app and Core (Home clock, reminders, activity, permissions, quiet hours, briefing, time picker, reminder confirmations, alarm steps, AI answers); optional 24-hour; synced through Core |
| Humble, warm personality; "Sir" | Neutral prompt, terse "Done." messages | **Done.** Personality in every chat; polite task replies; form of address configurable (default "Sir", or none) |
| Instant / Balanced / Deep modes | Not present | **Done.** Per user (Settings) or per message; FreeLLMAPI uses `auto:fast` / `auto:smart`; shorter or longer answers |
| Measured speed (first word, total) | Not measured | **Done.** Stored for every reply; shown under each reply and as averages on System → AI usage |
| AI knows the local date/time | No | **Done.** From the device's time zone |
| Wake word, tray, background service (Windows) | Push-to-talk; agent runs in a console | Not yet (next round) |
| Android foreground service / voice | System assistant gesture; app-open only | Not yet; platform limits apply |
| Semantic memory (embeddings) | Full-text search | Not yet |
| Calendar, Gmail, Drive, OneDrive, GitHub | None | Not yet (need your authorization per service) |
| Weather, calendar widgets | None | Not yet (weather needs a provider; calendar needs integration) |
| 3D core, resizable panels, background images | 2D animated core, draggable panels, background styles | Not yet |

## Risks and decisions
- **No framework changes.** FastAPI, PostgreSQL, Redis, Flutter and the
  Python agent stay.
- **Privacy:** FreeLLMAPI counts as cloud, so private chats never use it.
  Response modes don't change that.
- **Personality:** ULTRON is asked never to claim feelings or experiences,
  matching the request.
