# ULTRON first release — readiness checklist

Status as of 2026-11-10. ✅ = verified (where it says how), 🟡 = built and
tested in the sandbox/CI but not yet on your PC or phone, ❌ = not done.

| # | Criterion | Status | Evidence / what's left |
|---|---|---|---|
| 1 | Existing application works | ✅ | All earlier tests still pass; browser check against real Core |
| 2 | Windows frontend builds and runs | 🟡 | **Builds** on GitHub's Windows machine (App CI `build-windows`); not yet run on your PC |
| 3 | Android app builds and installs | 🟡 | Release APK builds here and in CI; **not installed** on the iQOO yet |
| 4 | FastAPI backend works | ✅ | 221 backend tests (real PostgreSQL/Redis); runs in Docker here |
| 5 | Cloud AI works | 🟡 | Router and adapters tested with fakes and the dev mock; needs your free API key for a real call |
| 6 | Local Ollama works | 🟡 | Adapter, loading states and warm-up tested; live run with `qwen3.5:4b` pending on your PC (no Ollama here) |
| 7 | Routing and fallback | ✅ | Tests: cloud first, local fallback, private → local only, cooldowns |
| 8 | Chat and streaming | ✅ | Tests + browser check (SSE stages, stop, retry) |
| 9 | Memory | ✅ | 9 backend + 4 app tests; recall into chat verified |
| 10 | File intelligence | ✅ (documents) | PDF/DOCX/XLSX/text with tests on real generated files; **images, scans and audio not supported** |
| 11 | Autonomous execution for authorized actions | ✅ (sandbox) | End-to-end with real Core + real agent process (Linux): organize, open app, workflow, status, multi-step write |
| 12 | Permission management | ✅ | Classes A/B/C, grants with expiry, master switch, emergency stop: tests + E2E |
| 13 | Windows agent functions | 🟡 | 36 tests on Linux + Windows CI; E2E on Linux; real Windows run pending |
| 14 | Android assistant within platform limits | 🟡 | VoiceInteractionService/session/recognizer compile into the APK; not run on a phone |
| 15 | Default assistant selection tested | ❌ | Needs the iQOO (no device or KVM emulator here) |
| 16 | Wake word tested, or fallback documented | ✅ (documented) | Not implemented; reasons and the system-gesture alternative in the Android guide |
| 17 | Voice interaction works | 🟡 | 22 voice/assistant tests with fakes; browser listened in headless Chrome; real mic/speaker pending |
| 18 | Device communication is secure | ✅ (sandbox) | Pairing codes + HTTPS with pinned certificate verified with a real HTTPS server here; phone pairing pending |
| 19 | Existing and new tests pass | ✅ | Backend 221, app 116, agent 36 (+1 Windows-only) |
| 20 | Documentation and release instructions | ✅ | `docs/ULTRON_*.md`, app and agent READMEs |

**Verdict:** not yet ready to call a complete first release. The software
is built and tested as far as possible without your devices; items 2, 3,
5, 6, 13, 14, 15 and 17 need the steps below.

## Steps for you (in order)
1. On the PC: `git pull`, `docker compose up -d --build`
   ([setup guide](ULTRON_SETUP_GUIDE.md)).
2. Add one free cloud AI key to `.env`; send a chat message → CLOUD badge.
3. Install Ollama + `qwen3.5:4b`; private chat → LOCAL badge
   ([WINDOWS_OLLAMA.md](WINDOWS_OLLAMA.md)).
4. Run the Windows app and the agent; work through the
   [Windows checklist](ULTRON_WINDOWS_GUIDE.md#4-verification-checklist-on-your-pc).
5. Turn on HTTPS, install the APK on the iQOO, pair, make ULTRON the
   assistant; work through the
   [Android checklist](ULTRON_ANDROID_GUIDE.md#7-verification-checklist-on-the-iqoo).
6. Report anything that fails; it gets fixed and re-tested.
