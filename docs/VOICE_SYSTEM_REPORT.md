# ULTRON voice system report

_Last updated: 2026-11-10._ Nothing here has been tested with a real
microphone or speaker on your devices yet.

## Phase 1 (2026-11-10): Windows voice fixed
- **Root cause:** the Windows `speech_to_text` plugin never reports a
  final result or "done" (and has no en-IN or Hindi), so the mic stayed on
  "listening".
- **Now (Windows):** the app records 16 kHz audio; ULTRON Core transcribes it
  with faster-whisper `small` (on your PC, English + Hindi). Recording stops
  1.2 s after you stop talking (or when you tap the mic, or at 30 s).
- **Everywhere:** a 75 s watchdog ends listening; instant listening state
  and sound; replies are spoken sentence by sentence as they stream.

## What exists
| Feature | Windows | Android | Status |
|---|---|---|---|
| Push-to-talk (mic button in chat, command bar, assistant screen) | ✓ recorded in the app, transcribed by Core (Whisper) | ✓ phone recognizer | Built, widget-tested with fake engines |
| Live transcript, mic level drives the visualizer | ✓ | ✓ | Built |
| Read replies aloud (TTS), speed setting, voice language | ✓ | ✓ | Built |
| Stop / interrupt reading by starting to talk | ✓ | ✓ | Built and tested |
| Assistant screen: greet, listen, act, speak result | ✓ (button) | ✓ (system assistant gesture) | Built; phone not tested |
| Private conversations | Mic allowed (on-device SAPI) | Mic **off** (recognizer may be online); offline voices only | Built (privacy rule) |

## Not built yet
| Feature | Why / plan |
|---|---|
| **Windows wake word** ("Hey ULTRON") | Planned: an open-source, local wake-word engine running in the Windows agent, off by default, with a visible "listening" indicator and a tray toggle |
| **Windows keyboard shortcut** to talk | Planned with the tray / background service |
| **Android wake word** | Android only allows always-on hotword detection for system apps. The supported way is the assistant gesture (long-press power/home) |
| Hands-free conversation (keep listening after a reply) | Planned (Windows first) |
| Language auto-detection | Uses the chosen voice language today |

## Rules that will stay
- The microphone is never used without a visible listening state.
- No hidden or background recording; wake-word listening (when added) is
  opt-in, local, and shown in the status bar/tray.
