"""Adapter for a local Ollama runtime (optional local AI / offline mode)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

import httpx

from ultron_core.ai.errors import (
    ModelNotInstalledError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderRequestError,
    ProviderUnavailableError,
)
from ultron_core.ai.providers.base import ChatProvider
from ultron_core.ai.types import (
    Availability,
    ChatRequest,
    ProviderKind,
    StreamEnd,
    StreamEvent,
    TextDelta,
)

_AVAILABILITY_TTL_SECONDS = 10.0
_MAX_ERROR_BODY = 2048
THINK_SETTINGS = ("false", "true", "low", "medium", "high", "default")


def model_matches(configured: str, installed: str) -> bool:
    """'llama3.2' matches 'llama3.2:latest'; tagged names must match exactly."""
    if configured == installed:
        return True
    return ":" not in configured and installed == f"{configured}:latest"


def think_value(setting: str) -> bool | str | None:
    """Map ULTRON_OLLAMA_THINK to Ollama's ``think`` field (None = omit)."""
    return {"false": False, "true": True, "default": None}.get(setting, setting)


class _InlineThinkFilter:
    """Hide a leading ``<think>…</think>`` block if a model puts its reasoning
    inside the answer text (older runtimes/imported models). Ollama normally
    returns reasoning in a separate ``thinking`` field, which is ignored."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._state = "start"  # start -> (thinking -> after_think ->) answer

    def feed(self, text: str) -> str:
        if self._state == "answer":
            return text
        if self._state == "after_think":
            # Drop the blank lines a model puts between reasoning and answer.
            text = text.lstrip()
            if text:
                self._state = "answer"
            return text
        self._buffer += text
        if self._state == "start":
            stripped = self._buffer.lstrip()
            if not stripped:
                return ""
            if len(stripped) < len(self.OPEN) and self.OPEN.startswith(stripped):
                return ""  # could still become "<think>": wait for more
            if not stripped.startswith(self.OPEN):
                self._state = "answer"
                out, self._buffer = self._buffer, ""
                return out
            self._state = "thinking"
        end = self._buffer.find(self.CLOSE)
        if end == -1:
            return ""
        rest = self._buffer[end + len(self.CLOSE) :]
        self._buffer = ""
        self._state = "after_think"
        return self.feed(rest)

    def flush(self) -> str:
        # An unfinished "<think" prefix that never completed is real text.
        out = self._buffer if self._state == "start" else ""
        self._buffer = ""
        return out


class OllamaProvider(ChatProvider):
    kind = ProviderKind.LOCAL

    def __init__(
        self,
        *,
        http: httpx.AsyncClient,
        base_url: str | None,
        model: str | None,
        context_char_budget: int,
        connect_timeout: float,
        read_timeout: float,
        think: str = "false",
        num_ctx: int | None = 8192,
        keep_alive: str | None = None,
        blocked_reason: str | None = None,
        name: str = "ollama",
    ) -> None:
        self.name = name
        self._http = http
        self._base_url = (base_url or "").rstrip("/")
        self.model = (model or "").strip() or None
        self.context_char_budget = context_char_budget
        self._timeout = httpx.Timeout(read_timeout, connect=connect_timeout)
        self._probe_timeout = httpx.Timeout(3.0, connect=min(connect_timeout, 3.0))
        self._think = think_value(think)
        self._num_ctx = num_ctx
        self._keep_alive = keep_alive
        # Set when the address violates the local-only policy (local_policy.py).
        self.blocked_reason = blocked_reason
        self._cached: tuple[float, Availability] | None = None

    def is_configured(self) -> bool:
        return bool(self._base_url and self.model and not self.blocked_reason)

    def missing_configuration(self) -> str | None:
        if self.blocked_reason:
            return self.blocked_reason
        if not self._base_url:
            return "local AI not set up (ULTRON_OLLAMA_BASE_URL is empty)"
        if not self.model:
            return "no local model chosen (ULTRON_OLLAMA_MODEL is empty)"
        return None

    def invalidate(self) -> None:
        self._cached = None

    async def availability(self) -> Availability:
        """Real check: the runtime answers AND the configured model is installed."""
        if not self.is_configured():
            return Availability(False, self.missing_configuration())
        now = time.monotonic()
        if self._cached and now - self._cached[0] < _AVAILABILITY_TTL_SECONDS:
            return self._cached[1]
        result = await self._probe()
        self._cached = (now, result)
        return result

    async def _probe(self) -> Availability:
        try:
            resp = await self._http.get(f"{self._base_url}/api/tags", timeout=self._probe_timeout)
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", [])]
        except (httpx.HTTPError, ValueError, AttributeError):
            return Availability(False, "local AI runtime (Ollama) is not running or not reachable")
        assert self.model is not None  # noqa: S101 - narrowed by is_configured
        if not any(model_matches(self.model, m) for m in models):
            return Availability(
                False,
                f"local model '{self.model}' is not installed",
                {"installed_models": models[:20]},
            )
        return Availability(True, None, {"installed_models": models[:20]})

    async def model_loaded(self) -> bool | None:
        """Whether the model is already in memory (Ollama /api/ps); None if unknown."""
        if not self.is_configured():
            return None
        try:
            resp = await self._http.get(f"{self._base_url}/api/ps", timeout=self._probe_timeout)
            resp.raise_for_status()
            names = [m.get("name", "") for m in resp.json().get("models", [])]
        except (httpx.HTTPError, ValueError, AttributeError):
            return None
        assert self.model is not None  # noqa: S101
        return any(model_matches(self.model, n) for n in names)

    async def warmup(self) -> bool:
        """Load the model into memory without generating anything.

        Returns True if it was already loaded. Raises ProviderError subclasses."""
        if not self.is_configured():
            raise ProviderNotConfiguredError(f"{self.name}: {self.missing_configuration()}")
        already = await self.model_loaded()
        payload: dict[str, object] = {"model": self.model, "messages": []}
        if self._keep_alive:
            payload["keep_alive"] = self._keep_alive
        try:
            resp = await self._http.post(
                f"{self._base_url}/api/chat", json=payload, timeout=self._timeout
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            self.invalidate()
            raise ProviderUnavailableError("local AI runtime (Ollama) is not running") from exc
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("local AI timed out while loading the model") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("local AI connection problem") from exc
        await self._raise_for_status(resp)
        return bool(already)

    def _payload(self, request: ChatRequest) -> dict[str, object]:
        messages = [{"role": "system", "content": request.system}]
        messages += [{"role": m.role, "content": m.content} for m in request.messages]
        options: dict[str, object] = {"num_predict": request.max_output_tokens}
        if self._num_ctx:
            # Ollama's default context can be as small as 4096 tokens, which
            # would silently cut off conversation history.
            options["num_ctx"] = self._num_ctx
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": options,
            # No "tools": replies are text only.
        }
        if self._think is not None:
            payload["think"] = self._think
        if self._keep_alive:
            payload["keep_alive"] = self._keep_alive
        return payload

    async def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        body = (await resp.aread())[:_MAX_ERROR_BODY].decode("utf-8", "replace").lower()
        if resp.status_code == 404 or "not found" in body:
            self.invalidate()
            raise ModelNotInstalledError(f"local model '{self.model}' is not installed")
        if "think" in body:
            raise ProviderRequestError(
                "the local model does not support the ULTRON_OLLAMA_THINK setting"
            )
        if "memory" in body:
            raise ProviderUnavailableError("local model could not be loaded (not enough memory)")
        if resp.status_code >= 500:
            raise ProviderUnavailableError("local AI runtime error")
        raise ProviderRequestError("local AI rejected the request")

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if not self.is_configured():
            raise ProviderNotConfiguredError(f"{self.name}: {self.missing_configuration()}")
        end = StreamEnd(model=self.model)
        think_filter = _InlineThinkFilter()
        produced_text = False
        try:
            async with self._http.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json=self._payload(request),
                timeout=self._timeout,
            ) as resp:
                await self._raise_for_status(resp)
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise ProviderUnavailableError("local AI reported an error")
                    # message.thinking (reasoning) is deliberately not shown.
                    text = think_filter.feed((chunk.get("message") or {}).get("content") or "")
                    if text:
                        produced_text = True
                        yield TextDelta(text)
                    if chunk.get("done"):
                        end = StreamEnd(
                            finish_reason=chunk.get("done_reason"),
                            input_tokens=chunk.get("prompt_eval_count"),
                            output_tokens=chunk.get("eval_count"),
                            model=chunk.get("model") or self.model,
                        )
                        break
        except ProviderError:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            self.invalidate()
            raise ProviderUnavailableError("local AI runtime (Ollama) is not running") from exc
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("local AI timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("local AI connection problem") from exc

        rest = think_filter.flush()
        if rest:
            produced_text = True
            yield TextDelta(rest)
        if not produced_text:
            reason = (
                "the local model used its whole output limit before answering"
                if end.finish_reason == "length"
                else "the local model returned an empty answer"
            )
            raise ProviderUnavailableError(reason)
        yield end
