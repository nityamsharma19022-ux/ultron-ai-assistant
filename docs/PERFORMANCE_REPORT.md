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

## Phase 2: speed (before → after)
Benchmark `scripts/benchmark_ai.py`, 3 runs per row, sandbox Core with
two stand-in cloud sources: **freellmapi** (configured first; first word
after 700 ms) and **custom** (400 ms). The stand-ins' delays are fixed, so
the gains come from ULTRON's choices, not from faster AI.

| Request | Before | After |
|---|---|---|
| Command "how is my pc doing" (command bar) | 957 ms | **6 ms** |
| Same sentence in chat | 756 ms (AI) | **16 ms** (no AI) |

Time to first word / total, normal routing:

| Mode | Before | After, first use | After, with speed history |
|---|---|---|---|
| Instant | 752 / 1060 ms (freellmapi) | **463 / 771 ms** (race → custom) | **454 / 762 ms** (custom) |
| Balanced | 750 / 1057 ms (freellmapi) | 752 / 1061 ms (no history yet) | **450 / 758 ms** (custom) |
| Deep | 748 / 1055 ms (freellmapi) | 755 / 1066 ms | 752 / 1060 ms (keeps the configured order on purpose) |

Forcing one source (benchmark rows `freellmapi` / `custom`) gives the same
times before and after (~750 ms / ~450 ms): choosing a source by hand
turns ranking and racing off. Files: `.ultron-bench/benchmark-before-sandbox-*.json`,
`benchmark-after-*.json` (not committed).

What changed:
- **Instant commands:** clear commands are planned by rules and never
  wait for an AI (they used to call the AI planner first).
- **Speed ranking:** cloud sources are tried fastest first, by average
  time to first word of their last 20 replies (14 days). Sources without
  data are tried before slower known ones so they get measured.
- **Instant race:** the two fastest sources start together; the first
  word wins and the other request is cancelled (not counted as a failure).
- **Fewer memories:** at most 5 recalled (3 in Instant), shorter prompts.
- **Ollama:** kept in memory (`keep_alive=-1`) and loaded when Core
  starts, so the first local reply doesn't wait ~10–30 s for loading.

### Ollama on your graphics card (GPU)
System → Local model → **Runs on** shows where the model runs (from
`ollama ps`). Without an NVIDIA card it will usually say CPU:
- Run `ollama ps` in PowerShell: the PROCESSOR column says `100% GPU`,
  `100% CPU` or a split.
- **AMD Radeon:** install the latest AMD Adrenalin driver and the latest
  Ollama; recent Ollama versions use supported Radeon cards automatically.
- **Intel/AMD integrated graphics:** usually stays on the CPU. Use a
  smaller model (e.g. `qwen3.5:2b`) or rely on cloud AI for speed.
- **Memory:** `keep_alive=-1` keeps the model (~3–4 GB for `qwen3.5:4b`)
  in RAM all the time. If your PC feels slow, set
  `ULTRON_OLLAMA_KEEP_ALIVE=30m` in `.env` and restart Core.

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
- Ollama now stays loaded by itself (System → Local model shows CPU/GPU).
- Leave the AI source order in Settings untouched so ULTRON can rank by
  speed; set it by hand only if you prefer a specific source.

## Measuring real speed on your PC
Run the benchmark (from the project folder, Core running):
`uv run scripts/benchmark_ai.py --label mypc`. It asks for your password,
signs in as a separate "ULTRON benchmark" device, restores your settings
and signs that device out at the end.

Every reply stores, measured by Core:
- **time to first word**, from the moment Core receives your message;
- **total time** to the end of the reply.

You can see them:
- under each reply in chat (e.g. `0.9 s → 2.4 s`);
- as averages per model on **System → AI usage (7 days)**.

## Not measured yet
- Real model latency on your PC (FreeLLMAPI, Ollama): run the benchmark
  there.
- App frame rate and memory use on Windows/Android.
- Tool execution time on the Windows agent (per-step start/finish times
  are already stored with each task).
