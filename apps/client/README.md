# ULTRON App (Windows + Android)

The Flutter app for ULTRON. It talks only to **ULTRON Core** (`apps/core`);
it never holds AI provider keys and never talks to Ollama directly.

What's in it (Phase 3):

- **Sign-in** to your ULTRON Core, with a "Test connection" check.
- **Chat** with streamed replies, progress stages (routing, loading the
  local model, generating), stop, retry, a CLOUD/LOCAL badge on each reply,
  conversation list, and **private** conversations (local AI only).
- **Animated AI visualizer** that reacts to the reply stage, the AI source,
  the connection, the microphone level and read-aloud.
- **System dashboard**: Core, database, Redis, AI sources, local model
  (with warm-up) and signed-in devices.
- **Settings**: AI routing (stored on Core), accent colour, animation
  level, voice, account, licences.
- **Voice**: push-to-talk and read-aloud using the device's own speech
  engines (see "Voice and privacy" below).

Not in Phase 3 (planned for 3b): offline cache and outbox, safe phone
pairing with TLS.

## Run the tests

```bash
flutter pub get
flutter analyze
flutter test
```

Tests use a fake ULTRON Core and fake speech engines; they make no network
calls.

## Windows

One-time setup:

1. Install the Flutter SDK (stable, 3.47.9 or newer) from
   <https://docs.flutter.dev/get-started/install/windows/desktop>. To keep
   everything on D:, extract it to `D:\ULTRON\tools\flutter` and add
   `D:\ULTRON\tools\flutter\bin` to your user `PATH`.
2. Install **Visual Studio 2022** (Community or Build Tools) with the
   **Desktop development with C++** workload.
3. Turn on **Developer Mode** (Settings → System → For developers); Flutter
   needs it to build plugins.
4. Check: `flutter doctor` (the Windows and Visual Studio lines should be
   green).

Run and build (in `D:\ULTRON\ultron-ai-assistant\apps\client`):

```powershell
flutter pub get
flutter run -d windows
```

```powershell
flutter build windows --release
```

The release build is in `build\windows\x64\runner\Release\` (run
`ultron_app.exe`; keep the whole folder together).

Start ULTRON Core first (`docker compose up -d` in the project folder) and
sign in with the default address `http://127.0.0.1:8000`.

## Android

One-time setup:

1. Install **Android Studio** (it brings the Android SDK), then
   `flutter doctor --android-licenses`.
2. For a real phone: enable Developer options → USB debugging, and connect
   it.

Run and build:

```bash
flutter run -d <device-id>
```

```bash
flutter build apk --release
```

The APK is `build/app/outputs/flutter-apk/app-release.apk`. It is signed
with the debug key, which is fine for installing on your own phone; set up
a release key before sharing it.

Which address to sign in with:

- **Emulator** → `http://10.0.2.2:8000` (the default on Android).
- **Real phone on your Wi-Fi** → `http://<your PC's LAN IP>:8000`, after
  allowing LAN access on the PC (`ULTRON_CORE_BIND_HOST=0.0.0.0` and a
  Windows Firewall rule for private networks only; see
  [docs/DEVELOPMENT.md](../../docs/DEVELOPMENT.md#6-let-the-android-app-reach-the-windows-backend)).
  This traffic is plain HTTP on your home network until TLS pairing
  (Phase 3b).

## Voice and privacy

| | Windows | Android |
|---|---|---|
| Voice input | Windows Speech (SAPI dictation), on the PC | System recogniser, usually Google's service, which may process audio online |
| Voice input in **private** chats | Allowed | **Off** (the app can't guarantee recognition stays on the phone) |
| Read aloud | Windows voices on the PC | Android text-to-speech |
| Read aloud in **private** chats | Allowed | Only with a voice that works offline; otherwise the app says so |

Windows notes: speech recognition needs a speech language installed
(Settings → Time & language → Speech). Windows support in the
`speech_to_text` plugin is marked beta by its authors, so please report
anything odd.

## Project layout

```
lib/
  core/        API client (REST + streamed replies), auth and tokens,
               settings, system status, theme
  features/    auth, shell (navigation), chat, visualizer, dashboard,
               settings, voice
  widgets/     shared widgets (glass panels, badges, indicators)
test/          unit and widget tests (fake backend, fake voice)
```

Fonts: Orbitron and Inter, SIL Open Font License (shown in the app's
licences page).
