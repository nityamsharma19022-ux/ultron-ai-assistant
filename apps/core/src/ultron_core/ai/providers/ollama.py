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


def model_matches(configured: str, installed: str) -> bool:
    """'llama3.2' matches 'llama3.2:latest'; tagged names must match exactly."""
    if configured == installed:
        return True
    return ":" not in configured and installed == f"{configured}:latest"


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
        name: str = "ollama",
    ) -> None:
        self.name = name
        self._http = http
        self._base_url = (base_url or "").rstrip("/")
        self.model = model
        self.context_char_budget = context_char_budget
        self._timeout = httpx.Timeout(read_timeout, connect=connect_timeout)
        self._probe_timeout = httpx.Timeout(2.0, connect=min(connect_timeout, 2.0))
        self._cached: tuple[float, Availability] | None = None

    def is_configured(self) -> bool:
        return bool(self._base_url and self.model)

    def missing_configuration(self) -> str | None:
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

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if not self.is_configured():
            raise ProviderNotConfiguredError(f"{self.name}: {self.missing_configuration()}")
        messages = [{"role": "system", "content": request.system}]
        messages += [{"role": m.role, "content": m.content} for m in request.messages]
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"num_predict": request.max_output_tokens},
        }
        end = StreamEnd(model=self.model)
        try:
            async with self._http.stream(
                "POST", f"{self._base_url}/api/chat", json=payload, timeout=self._timeout
            ) as resp:
                if resp.status_code == 404:
                    self.invalidate()
                    raise ModelNotInstalledError(f"local model '{self.model}' is not installed")
                if resp.status_code >= 500:
                    raise ProviderUnavailableError("local AI runtime error")
                if resp.status_code >= 400:
                    raise ProviderRequestError("local AI rejected the request")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise ProviderUnavailableError("local AI reported an error")
                    text = (chunk.get("message") or {}).get("content")
                    if text:
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
        yield end
