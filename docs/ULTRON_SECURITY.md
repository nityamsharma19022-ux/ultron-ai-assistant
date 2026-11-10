# ULTRON security

This extends [SECURITY.md](SECURITY.md) (credentials, private
conversations, local-only Ollama, validation, logging) with everything
added for tasks, agents, voice, documents and pairing.

## 1. Principles
- **Autonomous routine work, not unrestricted access.** ULTRON acts only
  through a fixed list of typed tools, only with your permissions, and
  devices only do what their own local configuration allows.
- **AI output is never executed.** Models return text. A plan is JSON that
  is validated against the tool registry; anything unknown is rejected.
- **Everything is visible.** Every task, step, approval, permission change,
  memory change, pairing and emergency stop is in the Activity history.
- **No hidden monitoring.** No background recording, no screen capture,
  no continuous listening.

## 2. Action classes and permissions
| Class | Examples | Behaviour |
|---|---|---|
| A — routine | open apps, read/search files, create folders and new documents, organize a folder, run your workflows, reminders, memories, AI writing | Runs without asking once you allow its scope (Tasks → Permissions, or "Always allow" when approving). Grants can expire and be revoked. |
| B — consequential | overwriting a file, moving over an existing file, deleting (to the Recycle Bin) | **Always asks**, every time. "Always allow" is never stored for B. |
| C — external / high-impact | messages, publishing, purchases, credential changes, sharing private data | **Always asks.** No class C tools exist yet; the rule is enforced for any added later. |

- **Master switch** (Tasks → Permissions): when off, tasks wait.
- **Emergency stop** (STOP ALL): cancels every active task, tells agents
  to stop running steps, and blocks new runs until you resume.
- Tasks show a preview of every step before anything runs that needs
  approval.

## 3. Devices and agents
- Each device has its own sign-in and can be signed out instantly
  (System → Devices). Refresh tokens rotate; reuse revokes the family.
- Agents receive only steps for tools they announced, for their own user,
  after Core's permission check.
- **Windows agent defence in depth:** file paths must be inside the
  folders listed in its `agent.toml` (no absolute paths, `..`, drive
  letters, UNC paths, device names or link escapes); apps and workflows are
  argument lists from that file and run without a shell; documents are
  written atomically; organize keeps an undo journal; deletes go to the
  Recycle Bin. The agent's sign-in is encrypted with Windows DPAPI.
- The phone only runs `phone.*` steps while ULTRON is open, using public
  Android APIs (no accessibility service, no special privileges).

## 4. Prompt injection
- Plans are made **before** execution from your request and the tool
  catalog only. Text read later (files, documents, AI output) can fill in
  content but can never add, remove or change steps.
- Document excerpts and file contents are given to models inside
  `<<<DOCUMENTS … >>>` / `<<<SOURCE … >>>` blocks with an explicit rule not
  to follow instructions inside them. Tests check the order and markers.
- Memories are given as "background facts, not instructions".

## 5. Pairing and transport
- **Pairing codes:** 8 characters from an unambiguous alphabet, single
  use, 10 minutes, stored only as a SHA-256 hash in Redis, redemption
  limited to 10 attempts per 10 minutes per address; optional platform
  lock.
- **HTTPS on your network:** `ultron-core tls-init` creates an EC P-256
  self-signed certificate (private key `0600`, git-ignored). The app pins
  the certificate's SHA-256 after you compare its short form with the PC;
  a certificate that differs from what Core reports stops pairing before
  the code is sent. After that the app trusts only that certificate (plus
  normal public CAs). The agent trusts it via `ca_file`.
- Plain HTTP is still possible on a trusted network but the pairing
  dialog marks it "Not encrypted".
- PostgreSQL and Redis are only on `127.0.0.1`; Core is on `127.0.0.1`
  unless you set `ULTRON_CORE_BIND_HOST` for the phone.

## 6. Voice
- Speech is turned into text on the device's speech service; Core never
  receives audio.
- Private conversations: voice input only where recognition stays on the
  device (Windows); read-aloud only with offline voices.
- No wake word: ULTRON never listens in the background (see the Android
  guide for why and the supported alternative).

## 7. Documents
- Up to 20 MB (configurable); text extracted on Core; identical files are
  stored once (SHA-256 per user); delete removes the text and all parts.
- Private documents can only be used in private (local-AI) conversations.

## 8. Checks run (2026-11-10)
- `pip-audit` on Core and agent dependencies: **no known vulnerabilities**.
- Secret scan of tracked files: no keys, certificates or `.env` tracked.
- `ruff` with the `S` (bandit) rules on Core and agent: clean.
- Tests for: unknown tools/arguments rejected, B/C always ask, emergency
  stop, permission expiry, agent boundaries (wrong device, wrong
  platform), path escapes, pairing code reuse/guessing, certificate
  mismatch, prompt-injection wrapping, private memory/document isolation.

## 9. Known gaps
| Gap | Notes |
|---|---|
| No external review / penetration test | Personal project; recommended before exposing Core outside your home network |
| Core is not meant to be on the public internet | Keep it on your LAN or behind a VPN; no cloud deployment yet |
| Single-process task engine | Fine for one PC; multi-process hosting needs Redis-based locking |
| Self-signed certificate rotation | Re-running `tls-init --force` means re-pairing devices |
| Agent runs as your Windows user | It can do what you can inside the allowed folders; keep `[roots]` narrow |
