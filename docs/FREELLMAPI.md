# Using FreeLLMAPI with ULTRON

[FreeLLMAPI](https://github.com/tashfeenahmed/freellmapi) is a router you
run on your PC. It gives one OpenAI-compatible address for the free tiers
of many AI providers and switches provider when one hits its limit.
ULTRON Core uses it as its **first cloud AI source**.

**Privacy:** FreeLLMAPI runs on your PC, but it sends your messages to the
cloud providers whose keys you added to it. ULTRON therefore treats it as
**cloud** AI: private conversations never use it (they use local Ollama
only). This is enforced in Core and covered by tests.

## 1. Find the API address and key
1. Open FreeLLMAPI's dashboard (`http://127.0.0.1:31415` for the desktop
   app).
2. **Keys** page → copy the unified key (`freellmapi-…`). Keep it secret.
3. Check which port serves the API (`/v1/chat/completions`). The desktop
   app's dashboard is on 31415; FreeLLMAPI's documentation uses 3001 for
   the API in a plain install. Test it in PowerShell:
   ```powershell
   curl.exe -H "Authorization: Bearer YOUR-KEY" http://127.0.0.1:31415/v1/models
   ```
   If that fails, try port 3001. Use the port that returns a model list.

## 2. Tell ULTRON Core
In `D:\ULTRON\ultron-ai-assistant\.env` (never committed):
```
ULTRON_FREELLMAPI_API_KEY=freellmapi-...your key...
ULTRON_FREELLMAPI_MODEL=auto
# Core in Docker (default setup):
ULTRON_CORE_FREELLMAPI_BASE_URL=http://host.docker.internal:31415/v1
# Core run directly on Windows instead:
ULTRON_FREELLMAPI_BASE_URL=http://127.0.0.1:31415/v1
```
Use port 3001 instead of 31415 if step 1 showed that. Model options:
`auto` (router decides), `auto:fast`, `auto:smart`, or an exact model id
from the gateway's model list (for example the Qwen model you tested).

Then restart Core:
```powershell
docker compose up -d core
```

## 3. Check it from ULTRON (not just from your PC)
In the app: **System → AI sources → FreeLLMAPI → Test**. This sends one
tiny message *through ULTRON Core* and shows the answer, the time and the
upstream model that answered. "Ready" next to FreeLLMAPI means Core sees
it as configured; only **Test** proves Core can actually reach it.

Then send a chat message: the reply shows the CLOUD badge, and
**System → AI usage** lists FreeLLMAPI with the real model used (from the
gateway's `X-Routed-Via` header) and token counts.

## How ULTRON uses it
- Order: FreeLLMAPI → Groq → Gemini → OpenRouter → custom → Anthropic,
  skipping any without a key; you can reorder in Settings → AI routing.
- If FreeLLMAPI is down or every free tier is exhausted (HTTP 429/5xx), it
  is paused briefly and the next source is tried; with no cloud source,
  local AI (Ollama) answers if installed.
- Requests are text only: ULTRON never sends tools to any model.

## Troubleshooting
| Test says | Fix |
|---|---|
| "Not set up: missing API key" | Add `ULTRON_FREELLMAPI_API_KEY` to `.env`, restart Core |
| "cannot reach provider" | FreeLLMAPI not running, or wrong port; in Docker use `host.docker.internal`, not `127.0.0.1` |
| "unauthorized" / 401 | Copy the key again from the Keys page |
| "rate limited" / quota | All free tiers are used up for now; add more providers in FreeLLMAPI or wait |
