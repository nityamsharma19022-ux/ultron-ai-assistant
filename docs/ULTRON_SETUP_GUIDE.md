# ULTRON setup guide

Everything runs on your Windows PC from `D:\ULTRON\ultron-ai-assistant`.
The phone connects to it over your home Wi-Fi.

| Part | Where | Guide |
|---|---|---|
| ULTRON Core (backend, database, Redis) | PC, Docker Desktop | this page |
| Local AI (Ollama, `qwen3.5:4b`) | PC | [WINDOWS_OLLAMA.md](WINDOWS_OLLAMA.md) |
| ULTRON app (Control Center) | PC and phone | [ULTRON_WINDOWS_GUIDE.md](ULTRON_WINDOWS_GUIDE.md), [ULTRON_ANDROID_GUIDE.md](ULTRON_ANDROID_GUIDE.md) |
| Windows agent (PC actions) | PC | [ULTRON_WINDOWS_GUIDE.md](ULTRON_WINDOWS_GUIDE.md) |

## 1. Get the code

```powershell
cd D:\ULTRON\ultron-ai-assistant
git status
git pull origin claude/fervent-lovelace-fqank5
```

## 2. Configure ULTRON Core

```powershell
Copy-Item .env.example .env   # only the first time
notepad .env
```

Set at least `ULTRON_POSTGRES_PASSWORD`, `ULTRON_REDIS_PASSWORD` and
`ULTRON_JWT_SECRET` (long random values). Optional cloud AI: add one or
more free-tier keys (`ULTRON_GROQ_API_KEY`, `ULTRON_GEMINI_API_KEY`,
`ULTRON_OPENROUTER_API_KEY`). `.env` is never committed.

## 3. Start it

```powershell
docker compose up -d --build
docker compose exec core ultron-core create-owner --email you@example.com
```

Check: `http://127.0.0.1:8000/health/ready` shows `"status": "ready"` and
database revision `0005` (migrations run automatically).

## 4. Let the phone reach the PC (optional, recommended with HTTPS)

1. Find the PC's Wi-Fi address: `ipconfig` → "IPv4 Address", e.g.
   `192.168.1.20`.
2. Create the HTTPS certificate for that address:
   ```powershell
   uv run --project apps\core ultron-core tls-init --host 192.168.1.20
   ```
   It writes `.ultron-core\tls\cert.pem` and `key.pem` (git-ignored) and
   prints the fingerprint.
3. In `.env`:
   ```
   ULTRON_CORE_BIND_HOST=0.0.0.0
   ULTRON_TLS_CERT_FILE=/run/ultron-tls/cert.pem
   ULTRON_TLS_KEY_FILE=/run/ultron-tls/key.pem
   ```
4. `docker compose up -d` and allow inbound TCP 8000 in Windows Firewall
   for **Private** networks only.
5. The address for devices is now `https://192.168.1.20:8000`.

## 5. Pair devices
On the PC app: **System → Devices → Pair a device**. On the phone: **Pair
with a code instead**, enter the address and the code, and check that the
security code matches. The Windows agent pairs with
`uv run ultron-agent pair`.

## 6. Daily use
- Talk: chat, or **Tasks** command bar ("organize my downloads", "open
  VS Code", "remind me to stretch at 9 pm", "prepare my weekly study plan").
- Allow routine actions once in **Tasks → Permissions**; important
  changes always ask. **STOP ALL** stops everything.
- Phone: make ULTRON the digital assistant and invoke it with the
  assistant gesture.

## 7. Backup and recovery
- Data lives in the Docker volumes `ultron_postgres_data` and
  `ultron_redis_data`. Back up the database:
  ```powershell
  docker compose exec postgres pg_dump -U ultron ultron > D:\ULTRON\backups\ultron-$(Get-Date -Format yyyyMMdd).sql
  ```
  Restore into a fresh stack with `psql` (stop `core` first).
- `scripts/windows/Invoke-UltronEnvironmentAudit.ps1` makes a verified
  copy of the project folder (without `.env` and dependencies).
- Memories can be exported anytime (Memory → ⋮ → Export).

## 8. Troubleshooting
| Symptom | Fix |
|---|---|
| App says "Core offline" | `docker compose ps`; check the address on the sign-in screen |
| Phone can't connect | Same Wi-Fi; `ULTRON_CORE_BIND_HOST=0.0.0.0`; firewall rule for Private networks; use the PC's IPv4 address |
| Tasks stay "Waiting for your PC" | Start the Windows agent (`uv run ultron-agent run`) |
| Tasks stay "Needs approval" | Approve, or allow the routine scope in Permissions |
| "Waiting: automation is paused" | Turn the master switch on / clear the emergency stop |
| Local AI unavailable | See [WINDOWS_OLLAMA.md](WINDOWS_OLLAMA.md) |
