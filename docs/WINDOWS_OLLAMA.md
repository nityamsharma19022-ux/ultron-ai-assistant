# ULTRON + Ollama on Windows

How to connect ULTRON to the Ollama model on your Windows PC and verify it.
All commands are for **PowerShell**, run from the repository folder
(e.g. `cd C:\path\to\ultron-ai-assistant`).

> In Windows PowerShell 5.1, `curl` is an alias for `Invoke-WebRequest`.
> This guide uses `Invoke-RestMethod` (or `curl.exe` explicitly) to avoid
> surprises.

## 1. How the connection works

| ULTRON backend runs… | Ollama address it uses | Setting |
|---|---|---|
| In Docker (`docker compose up`) | `http://host.docker.internal:11434` | `ULTRON_CORE_OLLAMA_BASE_URL` |
| Directly on Windows (`uv run ultron-core serve`) | `http://127.0.0.1:11434` | `ULTRON_OLLAMA_BASE_URL` |

Inside a container, `localhost` is the container itself, so the Docker
backend uses `host.docker.internal`, which Docker Desktop routes to your PC.

Use `127.0.0.1` rather than `localhost` for direct runs: on Windows,
`localhost` can resolve to IPv6 `::1` first, while Ollama listens on IPv4
`127.0.0.1` only, which can cause delays or connection failures.

**Only the backend talks to Ollama.** The ULTRON app (Phase 3) talks to
ULTRON Core, never to Ollama directly, so no app or website ever needs
Ollama's address. ULTRON refuses Ollama addresses that are not on this
machine (anything other than `127.0.0.1`, `localhost`, `::1`,
`host.docker.internal` or the Compose `ollama` service), and a backend
marked `ULTRON_DEPLOYMENT=cloud` never uses local AI. The only exception is
a deliberately secured remote Ollama: `ULTRON_OLLAMA_ALLOW_REMOTE=true`
**and** an `https` address.

**Keep Ollama private:** leave Ollama on its default `127.0.0.1:11434`. Do
not set `OLLAMA_HOST=0.0.0.0`; ULTRON doesn't need it, and it would expose
Ollama to your network. Docker Desktop reaches a `127.0.0.1`-only Ollama
through `host.docker.internal`.

## 2. Check Ollama

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/version
```

```powershell
ollama list
```

`qwen3.5:4b` must appear exactly like that. Quick reply test:

```powershell
$body = @{ model = "qwen3.5:4b"; messages = @(@{ role = "user"; content = "Say hello in one sentence." }); stream = $false; think = $false } | ConvertTo-Json -Depth 5
(Invoke-RestMethod http://127.0.0.1:11434/api/chat -Method Post -Body $body -ContentType "application/json").message.content
```

Check that Ollama is only listening locally (should show `127.0.0.1`):

```powershell
Get-NetTCPConnection -LocalPort 11434 -State Listen | Select-Object LocalAddress, LocalPort
```

## 3. Configure ULTRON

New setup: `Copy-Item .env.example .env`, then set your passwords and JWT
secret as described in [DEVELOPMENT.md](DEVELOPMENT.md).

Existing `.env`: make sure these lines exist (add any that are missing):

```
ULTRON_OLLAMA_BASE_URL=http://127.0.0.1:11434
ULTRON_CORE_OLLAMA_BASE_URL=http://host.docker.internal:11434
ULTRON_OLLAMA_MODEL=qwen3.5:4b
ULTRON_OLLAMA_THINK=false
ULTRON_OLLAMA_NUM_CTX=8192
ULTRON_OLLAMA_KEEP_ALIVE=
ULTRON_OLLAMA_ALLOW_REMOTE=false
ULTRON_AI_MAX_REPLY_SECONDS=300
ULTRON_AI_STREAM_KEEPALIVE_SECONDS=10
```

| Setting | Why |
|---|---|
| `ULTRON_OLLAMA_THINK=false` | Qwen 3.5 can "think" before answering. Off = fast replies. Use `true`/`low`/`medium`/`high` for more careful answers (slower; the reasoning itself is never shown). |
| `ULTRON_OLLAMA_NUM_CTX=8192` | Ollama's default context can be only 4096 tokens, which would cut off conversation history. Lower it (e.g. `4096`) if the model fails to load for lack of memory. |
| `ULTRON_OLLAMA_KEEP_ALIVE` | e.g. `30m` keeps the model loaded longer so replies start faster. |
| `ULTRON_AI_MAX_REPLY_SECONDS` | Hard limit for one reply, including model loading (default 300). Longer replies stop with error code `timeout` (HTTP 504 for non-streamed requests); any text so far is kept as `incomplete`. |
| `ULTRON_AI_STREAM_KEEPALIVE_SECONDS` | While waiting (e.g. model loading) the stream sends a `: keep-alive` line at this interval so connections don't time out. |

## 4. Start ULTRON (Docker)

```powershell
docker compose up -d --build
```

```powershell
docker compose ps
```

Check the container can reach Ollama on your PC:

```powershell
docker compose exec core python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/version').read())"
```

Readiness should show `"local_ai": {"status": "ok", ..., "model": "qwen3.5:4b"}`:

```powershell
Invoke-RestMethod http://localhost:8000/health/ready | ConvertTo-Json -Depth 5
```

First time only, create the owner account:

```powershell
docker compose exec core ultron-core create-owner --email you@example.com
```

## 4b. Warm-up and loading states

Load the model before the first chat (the app will do this on start):

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/ai/local/warmup -Method Post -Headers $h
```

(`$h` comes from the login in §7.) `GET /api/v1/ai/status` shows
`model_loaded` for Ollama.

Streamed replies report what is happening, so the app can show it:

| Event | Meaning | Suggested UI |
|---|---|---|
| `status` `{"phase": "routing"}` | Choosing a provider | "Thinking…" |
| `status` `{"phase": "loading_model", ...}` | Local model is being loaded into memory | "Loading local model…" |
| `status` `{"phase": "waiting", ...}` | Request sent, waiting for the first words | spinner |
| `provider.selected` + `status` `{"phase": "generating"}` | Text is coming; says cloud or local | "Local AI" / "Cloud AI" badge |
| `delta` | A piece of the reply | append text |
| `message.completed` / `message.cancelled` / `error` | Finished | stop spinner; show error message |
| `: keep-alive` (comment line) | Still working | ignore |

## 5. Run the automatic test (recommended)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\Test-UltronOllama.ps1 -Email you@example.com
```

It asks for your ULTRON password and checks: Ollama reachable and not
exposed, model installed, direct Ollama reply, ULTRON readiness, container →
host connection, **warm-up**, a real chat through ULTRON (JSON and streamed,
with **loading-state events**), a private conversation, **cloud → local
fallback** and **unavailable-model handling**.
For the last two it starts two temporary ULTRON containers (ports 8001 and
8002, removed afterwards) with test settings; your `.env` is not changed and
no real cloud provider is called. At the end it restores your AI
preferences, deletes its test conversations and signs its test device out.

Backend running without Docker? Add `-NoDocker` (skips the container,
fallback and missing-model checks; use step 6 for those).

## 6. Run the live pytest suite (optional, developers)

Needs [uv](https://docs.astral.sh/uv/) and Postgres + Redis running
(`docker compose up -d postgres redis`). Uses a separate `ultron_test`
database; your data isn't touched. From `apps\core`:

```powershell
$env:ULTRON_TEST_OLLAMA_URL = "http://127.0.0.1:11434"
$env:ULTRON_TEST_OLLAMA_MODEL = "qwen3.5:4b"
uv run pytest -m ollama_live -v -s
```

Eleven tests: runtime reachable, missing model reported, missing model chat
error, offline + missing model is not claimed as offline AI, missing model
can't warm up, model installed, real streamed reply (prints the reply and
timing), warm-up of the real model, cloud failure → real local fallback,
private → local only, and the full chat API with the real model.

## 7. Manual chat test through ULTRON

```powershell
$login = @{ email = "you@example.com"; password = (Read-Host "Password"); device_name = "PowerShell"; platform = "windows" } | ConvertTo-Json
$token = (Invoke-RestMethod http://localhost:8000/api/v1/auth/login -Method Post -Body $login -ContentType "application/json").access_token
$h = @{ Authorization = "Bearer $token" }
```

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/ai/status -Headers $h | ConvertTo-Json -Depth 5
```

```powershell
$conv = Invoke-RestMethod http://localhost:8000/api/v1/conversations -Method Post -Headers $h -Body "{}" -ContentType "application/json"
$msg = @{ content = "Hello ULTRON, who are you?" } | ConvertTo-Json
$reply = Invoke-RestMethod "http://localhost:8000/api/v1/conversations/$($conv.id)/messages" -Method Post -Headers $h -Body $msg -ContentType "application/json"
$reply.assistant_message | Select-Object provider, provider_kind, model, fallback_used, content
```

Private conversation:

```powershell
$priv = Invoke-RestMethod http://localhost:8000/api/v1/conversations -Method Post -Headers $h -Body '{"is_private": true}' -ContentType "application/json"
(Invoke-RestMethod "http://localhost:8000/api/v1/conversations/$($priv.id)/messages" -Method Post -Headers $h -Body $msg -ContentType "application/json").routing
```

Streaming (watch the events arrive):

```powershell
'{"content": "Count to five.", "stream": true}' | Out-File -Encoding ascii stream-body.json
curl.exe -N -X POST "http://localhost:8000/api/v1/conversations/$($conv.id)/messages" -H "Authorization: Bearer $token" -H "Content-Type: application/json" --data-binary "@stream-body.json"
```

(A body file avoids quoting differences between Windows PowerShell 5.1 and
PowerShell 7.)

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| Container check fails (`host.docker.internal` unreachable) | Use Docker Desktop (it provides `host.docker.internal`) and restart it. With a Docker engine inside WSL without Docker Desktop, run the backend directly on Windows instead (DEVELOPMENT.md §5). Don't expose Ollama with `OLLAMA_HOST=0.0.0.0` to work around it. |
| `local model 'qwen3.5:4b' is not installed` | `ollama list` shows the exact name; set `ULTRON_OLLAMA_MODEL` to it, then `docker compose up -d core`. |
| `local AI runtime (Ollama) is not running` | Start Ollama from the Start menu; check `Invoke-RestMethod http://127.0.0.1:11434/api/version`. |
| First reply takes long | The model is loading into memory. Later replies are faster; `ULTRON_OLLAMA_KEEP_ALIVE=30m` keeps it loaded. |
| `could not be loaded (not enough memory)` | Lower `ULTRON_OLLAMA_NUM_CTX` (e.g. `4096`) or close other GPU-heavy apps. |
| `used its whole output limit before answering` | Happens with thinking on. Set `ULTRON_OLLAMA_THINK=false` or raise `ULTRON_AI_MAX_OUTPUT_TOKENS` (e.g. `4096`). |
| `does not support the ULTRON_OLLAMA_THINK setting` | Set `ULTRON_OLLAMA_THINK=default`. |
| `Ollama address '…' is not on this machine` | Use `http://127.0.0.1:11434` (direct run) or `http://host.docker.internal:11434` (Docker). See §1 for remote setups. |
| Reply stops with `timeout` | The model needed longer than `ULTRON_AI_MAX_REPLY_SECONDS`; warm it up first, or raise the limit. |
| Script blocked by execution policy | Run it with `powershell -ExecutionPolicy Bypass -File ...` as shown (affects only that run). |
