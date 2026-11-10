# ULTRON on Windows

Two programs run on your PC besides ULTRON Core: the **ULTRON app**
(Control Center) and the **ULTRON agent** (does the PC actions).

## 1. The ULTRON app

Prerequisites (once): Flutter SDK 3.47.9+ (e.g. `D:\ULTRON\tools\flutter`
on your PATH), Visual Studio 2022 with **Desktop development with C++**,
Windows **Developer Mode** on. Check with `flutter doctor`.

```powershell
cd D:\ULTRON\ultron-ai-assistant\apps\client
flutter pub get
flutter run -d windows                 # development
flutter build windows --release        # build\windows\x64\runner\Release\ultron_app.exe
```

No Visual Studio? Every push builds the Windows app on GitHub
(Actions → **ULTRON App CI** → artifact **ultron-windows**). Unzip it and
run `ultron_app.exe`.

Sign in with `http://127.0.0.1:8000` (or `https://…` if you turned HTTPS
on) and your owner email and password.

## 2. The ULTRON agent

```powershell
cd D:\ULTRON\ultron-ai-assistant\apps\agent
uv sync
uv run ultron-agent init        # creates ..\..\.ultron-agent\agent.toml
notepad ..\..\.ultron-agent\agent.toml
uv run ultron-agent check
uv run ultron-agent pair        # code from the app: System → Devices → Pair a device
uv run ultron-agent run
```

`agent.toml` decides what ULTRON may touch:

```toml
[server]
url = "http://127.0.0.1:8000"
# With HTTPS: url = "https://127.0.0.1:8000" and
# ca_file = "D:\\ULTRON\\ultron-ai-assistant\\.ultron-core\\tls\\cert.pem"

[roots]                      # folders: "downloads/report.pdf" in tasks
downloads = "%USERPROFILE%\\Downloads"
documents = "%USERPROFILE%\\Documents"
ultron = "D:\\ULTRON\\ultron-ai-assistant"

[apps]                       # apps ULTRON may open or switch to
"VS Code" = { command = ["%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\Code.exe"], window_title = "Visual Studio Code" }
"Chrome" = { command = ["C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"], window_title = "Chrome" }

[workflows."Dev environment"]   # "run the dev environment workflow"
open_apps = ["VS Code"]
commands = [["docker", "compose", "up", "-d"]]
cwd = "ultron"
```

Start automatically at sign-in:
`.\scripts\windows\Install-UltronAgent.ps1` (remove with `-Uninstall`).
Undo the last "organize": `uv run ultron-agent undo`.

## 3. What to try (and check in Tasks → Activity)
| Say or type | What happens |
|---|---|
| "how is my PC doing" | CPU, memory, disk, battery |
| "open VS Code" / "switch to Chrome" | Opens / brings the window to the front |
| "organize my downloads" (or "… by date") | Sorts files into folders (asks first until you allow it) |
| "run the dev environment workflow" | Your fixed commands |
| "find my physics notes" | File search in allowed folders |
| "prepare my weekly study timetable" | AI writes it; agent saves it to `documents/…` |

## 4. Verification checklist (on your PC)
- [ ] `flutter run -d windows` opens the app; sign-in works
- [ ] `uv run ultron-agent check` shows your folders as OK
- [ ] The agent shows as Online in System → Agents
- [ ] "open VS Code" opens it; "switch to VS Code" brings it forward
- [ ] "organize my downloads" asks, then sorts; `ultron-agent undo` restores
- [ ] A workflow runs and its result appears in the task
- [ ] Install-UltronAgent.ps1: the agent starts after signing in to Windows
- [ ] Local AI: Ollama with `qwen3.5:4b` answers a private chat
