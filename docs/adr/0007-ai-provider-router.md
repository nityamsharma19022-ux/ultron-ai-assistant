# ADR-0007: AI provider router (cloud-first, local-fallback)

- **Status:** Accepted
- **Date:** 2026-11-09

## Context
ULTRON must prefer cloud AI (free tiers first), fall back to a local model
when cloud access fails, quotas run out or the device is offline, keep
private conversations off the cloud, and never pretend a local model exists.

## Decision
- One small provider interface (`stream(ChatRequest) -> text deltas + end`),
  text in / text out, **no tools** sent to any model.
- Adapters: OpenAI-compatible HTTP (Groq, Gemini, OpenRouter, custom) via
  httpx; Anthropic via the official `anthropic` SDK (retries off so the
  router fails over immediately; server-side refusal fallback on); Ollama
  native API for local AI; a development-only mock.
- Every adapter maps failures into shared categories (not configured, auth,
  rate limited, quota exhausted, unavailable, offline, model not installed,
  invalid request, refused). The router acts only on the category.
- Router rules: candidates from user preferences (`auto`, `cloud_only`,
  `local_only`, preferred cloud order); private → local only; skip
  unconfigured providers, providers in cooldown and uninstalled local
  models; fall through on failures before the first token; after a
  connection failure skip remaining cloud providers (offline); never retry
  a reply elsewhere once text has streamed; refusals and invalid requests
  are not retried elsewhere.
- Cooldowns in Redis (with in-process fallback): rate limit ≈ 60 s or
  `Retry-After`, quota 1 h, outage 30 s, auth failure 10 min.
- Each reply records provider, cloud/local, model, `fallback_used` and the
  list of attempts; the API returns them to the app.

## Alternatives
- LiteLLM or a similar gateway: large dependency surface for what is a small
  routing layer; harder to guarantee the privacy rule and honest reporting.
- Provider SDKs for every provider: more dependencies; the OpenAI-compatible
  HTTP API covers the free-tier providers uniformly.

## Consequences
- New providers need only an adapter and error mapping.
- Mid-reply failures produce an `incomplete` message instead of a blended
  answer.
