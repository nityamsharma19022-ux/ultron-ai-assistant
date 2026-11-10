# ULTRON known issues and limitations

_Last updated: 2026-11-10._ Open bugs: **none known**. Limitations:

## Needs your devices
- Nothing has run on your Windows PC or iQOO phone yet. Checklists:
  [Windows](ULTRON_WINDOWS_GUIDE.md#4-verification-checklist-on-your-pc),
  [Android](ULTRON_ANDROID_GUIDE.md#7-verification-checklist-on-the-iqoo).
- Real cloud AI needs one free API key in `.env`; real local AI needs
  Ollama with `qwen3.5:4b` on the PC.
- Windows toast notifications (`pc.notify`) can't be tested in the Linux
  sandbox.

## Limitations by design or platform
- **Wake word:** Android only lets system apps listen for a hotword. Use
  the assistant gesture. A Windows wake word is planned, not built.
- **Phone in the background:** Android stops background work, so phone
  steps and metrics only run while ULTRON is open.
- **Device metrics** are kept for 3 minutes; a device that stops sending
  disappears from the Devices panel.
- **Quiet hours** use the UTC offset of the device that saved them; after a
  daylight-saving change, save them again.

## Not built yet
- Semantic (vector) memory search; full-text search only.
- Offline cache and sync between devices.
- Images, scanned PDFs and audio can't be read.
- Keyboard/mouse automation on Windows.
- External integrations (calendar, email, GitHub).
- Custom background image; visualizer "executing"/"error" states.
- Agent tokens have the same rights as an app sign-in (scoped agent tokens
  planned). Keep `agent.toml` and the agent's token store private.

## Security notes
- `web.read` checks every address and redirect against private networks
  before connecting. Between that check and the connection, a malicious
  DNS server could in theory return a different address (DNS rebinding).
  Risk is low (Core must be asked to read that page, and only text comes
  back), but it is not fully closed.
- The JSON export is not encrypted. Store it like any private file.

## Sandbox-only notes (don't affect your PC)
- The sandbox builds the Core image with an extra CA certificate for its
  network proxy (`scratchpad/Dockerfile.sandbox`); the committed
  `Dockerfile` is unchanged.
