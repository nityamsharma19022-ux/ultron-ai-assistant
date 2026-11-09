# ADR-0003: Technology stack

- **Status:** Accepted (approved 2026-11-09)
- **Date:** 2026-11-09

## Context
ULTRON targets Android and Windows, must favour free/open-source tools, and
needs strong AI/speech library support.

## Decision
- **Client:** Flutter (one codebase for Android + Windows), SQLite via
  drift for offline storage.
- **Backend:** Python 3.12 + FastAPI, SQLAlchemy 2 + Alembic, arq for
  Redis-backed background jobs.
- **AI:** provider router over cloud free tiers (e.g. Gemini, Groq,
  OpenRouter), optional paid providers, and Ollama locally.
- **Speech:** faster-whisper (STT), Piper (TTS), platform TTS as fallback.

## Alternatives considered
- *Kotlin/Compose Multiplatform:* strong on Android, Windows desktop
  support less mature for this use case.
- *Electron/Tauri + separate Android app:* two client codebases.
- *Node.js backend:* fine for APIs, weaker local AI/speech ecosystem than
  Python.

## Consequences
- Two languages (Dart + Python) in one repo.
- Python gives direct access to Whisper, embeddings and model tooling.
