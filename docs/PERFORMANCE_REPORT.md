# ULTRON performance report

_Measured 2026-11-10 in Claude Code's cloud sandbox (Linux, 4 CPUs, real
PostgreSQL + Redis, a real ULTRON Core server over HTTP)._ These are
**ULTRON's own** times: the AI was a stand-in gateway that answers
instantly, so the numbers show what Core adds, not how fast a real model
is. Real AI speed is measured on your PC automatically (see below).

## Core overhead per chat message
From "message sent" to "first word arrives", 20 messages, 20 saved
memories (recall runs every time):

| Measurement | Median | Max |
|---|---|---|
| Server-measured, from receipt to first word | 15.5 ms | 28 ms |
| Client-measured (adds the HTTP hop) | 20 ms | — |

All three response modes add the same overhead (18–19 ms in the client).
They differ only in the model and answer length they ask for. The
stand-in gateway confirmed Instant → `auto:fast`, Balanced → `auto`,
Deep → `auto:smart` (15 requests each).

## Speech-to-text (Phase 1)
faster-whisper on the CPU (int8, sandbox: 4 cores), 4.1 s English
command "Open Notepad and remind me to call mom at 9 PM" (synthetic
voice):

| Model | Time to text | Result |
|---|---|---|
| base | 1.1 s | "…call Mama to IMPM" (wrong) |
| small (chosen) | 2.2 s | "Open Notepad and remind me to call mom at 9pm." (correct) |

- Loading `small` takes about 7 s once (first time: plus the ~500 MB
  download). **Prepare voice** in Settings does this ahead of time.
- Hindi needs the language hint (the app sends your voice language):
  without it, Whisper mis-detected the synthetic Hindi voice.
- Silence is detected in the app and never sent; the app also stops
  recording 1.2 s after you stop talking, so a short command needs no
  button press.
- Your PC's speed will differ: Settings → Voice shows the engine, and
  Core logs each transcription's time (never the words).

## Other requests (30 runs each)
| Request | Median | Max |
|---|---|---|
| Conversation search (full-text) | 6.6 ms | 11.4 ms |
| Memory search | 5.4 ms | 26.5 ms |
| Health check (database + Redis + local AI probe) | 3.4 ms | 5.7 ms |
| Task list | 5.1 ms | 65.2 ms |

## What this means
Core adds about **0.02 s**. On your PC, almost all waiting time is the AI
model itself (FreeLLMAPI's chosen provider, or Ollama loading
`qwen3.5:4b`). For faster replies:
- Use **Instant** mode (FreeLLMAPI `auto:fast`, shorter answers).
- Keep Ollama warm: System → Local model → **Warm up**.
- Put the fastest provider first in FreeLLMAPI.

## Measuring real speed on your PC
Every reply stores, measured by Core:
- **time to first word**, from the moment Core receives your message;
- **total time** to the end of the reply.

You can see them:
- under each reply in chat (e.g. `0.9 s → 2.4 s`);
- as averages per model on **System → AI usage (7 days)**.

## Not measured yet
- Real model latency on your PC (FreeLLMAPI, Ollama): appears in the app
  as you use it.
- App frame rate and memory use on Windows/Android.
- Tool execution time on the Windows agent (per-step start/finish times
  are already stored with each task).
