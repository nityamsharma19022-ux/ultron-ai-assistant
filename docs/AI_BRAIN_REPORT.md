# ULTRON AI brain report

How ULTRON decides what to do with a message or command, and which model
answers. _Last updated: 2026-11-10._

## Pipeline for a chat message
1. **Context:** the active operating mode, response mode (Instant /
   Balanced / Deep), form of address, time format and the device's local
   time.
2. **Classification:** `ai/profiles.py` classifies the message (chat,
   reasoning, coding, writing, summarize). Deep mode turns small talk into
   reasoning; Developer mode always counts as coding.
3. **Memory:** pinned memories plus the best full-text matches, limited to
   the conversation's project. Instant mode uses half as many.
   Documents attached to the message add their relevant parts.
4. **Routing** (`ai/router.py`):
   - Cloud first, in your order (FreeLLMAPI → Groq → Gemini → OpenRouter →
     custom → Anthropic), skipping any without a key.
   - Per kind of request, preferred providers go first
     (`ULTRON_AI_TASK_PROFILES`).
   - Rate limits and outages pause a provider briefly and move to the next.
   - Offline or no cloud: local Ollama.
   - Private conversations: local AI only, always.
5. **Model tier:** with FreeLLMAPI on `auto`, Instant uses `auto:fast`,
   Deep uses `auto:smart`, Balanced uses `auto` (configurable). Exact
   models stay fixed.
6. **Answer:** streamed (SSE). Time to the first word and the total are
   measured and stored. The real upstream model (FreeLLMAPI's
   `X-Routed-Via`) and token counts are recorded.

## Pipeline for a command (actions)
1. **Fixed rules first:** open/switch/close app (with everyday names:
   files → File Explorer), open a web address, organize a folder, remind,
   remember, run a workflow, status. These work without AI.
2. **Otherwise the AI planner:** it sees the tool catalog and your setup
   and returns a JSON plan. Every tool and argument is validated.
3. **Permissions:** autonomy level 0–5 per area. Important actions
   (delete, close app, overwrite) always ask.
4. **Engine:** runs steps on Core, the PC or the phone, with retries,
   verification, time limits, notifications and an automatic safety
   pause.
5. **Polite report**, e.g. "Certainly, Sir. Reminder set for today at
   9:30 PM."

## Models are text-only
No model is ever given tools to call directly. Actions only happen
through the validated planner and permission system. This is a deliberate
safety choice (see `docs/SECURITY.md`).

## Not built yet
- Embeddings / semantic memory search (FreeLLMAPI offers `/v1/embeddings`;
  planned with pgvector).
- Vision (image understanding) through a vision-capable model.
- Conversation summaries for very long chats (older messages are trimmed
  today).
- Parallel step execution (steps run in order).
