# ULTRON Windows agent

A small background program for your Windows PC. It signs in to ULTRON Core
as this PC and runs the **PC steps** of ULTRON tasks: opening apps,
finding, reading and organizing files, creating documents, running your
workflows, and reporting PC status.

It only acts on what **you list in its config**:

- folders (`[roots]`): file tools never leave them;
- apps (`[apps]`): only these can be opened or switched to;
- workflows (`[workflows]`): fixed commands, run without a shell.

ULTRON Core decides *whether* a step may run (your permissions, approvals,
emergency stop); the agent decides *what is possible* on this PC. Both must
agree. AI output is never run as a command.

## Set up (Windows, PowerShell)

Needs Python 3.12+ via [uv](https://docs.astral.sh/uv/) (already used for
ULTRON Core).

```powershell
cd D:\ULTRON\ultron-ai-assistant\apps\agent
uv sync
uv run ultron-agent init        # creates ..\..\.ultron-agent\agent.toml
notepad ..\..\.ultron-agent\agent.toml   # set folders, apps, workflows
uv run ultron-agent check       # shows folders (OK/MISSING), apps, tools
uv run ultron-agent login       # your ULTRON email and password
uv run ultron-agent run         # leave this running
```

The config and sign-in live in `D:\ULTRON\ultron-ai-assistant\.ultron-agent\`
(git-ignored). The sign-in is encrypted with Windows DPAPI for your Windows
account.

To start it automatically when you sign in to Windows, see
`scripts/windows/Install-UltronAgent.ps1`.

## Tools

| Tool | What it does | Class |
|---|---|---|
| `pc.status` | CPU, memory, disk space, battery, uptime | A |
| `pc.apps.list` / `pc.apps.open` / `pc.apps.focus` | List, open, bring to front | A |
| `pc.files.list` / `search` / `read` | Browse, find by name, read text/MD/PDF/DOCX | A |
| `pc.files.create_folder` / `write` | New folders and documents (.txt .md .docx .csv .json) | A (overwrite: B) |
| `pc.files.move` / `organize` | Move/rename; sort a folder by type or month (with undo) | A (overwrite: B) |
| `pc.files.delete` | Move to the Recycle Bin | B (always asks) |
| `pc.workflows.run` | Run one of your named workflows | A |

Undo the last "organize": `uv run ultron-agent undo`.

## Tests

```bash
uv run pytest
```
