"""Adapter for OpenAI-compatible chat APIs (Groq, Google Gemini's OpenAI
endpoint, OpenRouter, or any custom compatible endpoint)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from pydantic import SecretStr

from ultron_core.ai.errors import (
    ProviderError,
    ProviderNotConfiguredError,
    ProviderOfflineError,
    ProviderUnavailableError,
    classify_http_status,
    parse_retry_after,
)
from ultron_core.ai.providers.base import ChatProvider
from ultron_core.ai.types import ChatRequest, ProviderKind, StreamEnd, StreamEvent, TextDelta

_MAX_ERROR_BODY = 4096


class OpenAICompatibleProvider(ChatProvider):
    kind = ProviderKind.CLOUD

    def __init__(
        self,
        *,
        name: str,
        http: httpx.AsyncClient,
        base_url: str | None,
        api_key: SecretStr | None,
        model: str | None,
        context_char_budget: int,
        connect_timeout: float,
        read_timeout: float,
        extra_headers: dict[str, str] | None = None,
        include_usage: bool = False,
    ) -> None:
        self.name = name
        self._http = http
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = api_key
        self.model = model
        self.context_char_budget = context_char_budget
        self._timeout = httpx.Timeout(read_timeout, connect=connect_timeout)
        self._extra_headers = extra_headers or {}
        # Ask for token counts in the stream (only where the API supports it).
        self._include_usage = include_usage

    def is_configured(self) -> bool:
        return bool(
            self._base_url
            and self.model
            and self._api_key is not None
            and self._api_key.get_secret_value().strip()
        )

    def missing_configuration(self) -> str | None:
        missing = []
        if self._api_key is None or not self._api_key.get_secret_value().strip():
            missing.append("API key")
        if not self.model:
            missing.append("model")
        if not self._base_url:
            missing.append("base URL")
        return f"missing {', '.join(missing)}" if missing else None

    def _payload(self, request: ChatRequest) -> dict[str, object]:
        messages = [{"role": "system", "content": request.system}]
        messages += [{"role": m.role, "content": m.content} for m in request.messages]
        # Deliberately no "tools"/"functions": responses are text only.
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "max_tokens": request.max_output_tokens,
        }
        if self._include_usage:
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if not self.is_configured():
            raise ProviderNotConfiguredError(f"{self.name}: {self.missing_configuration()}")
        assert self._api_key is not None  # noqa: S101 - narrowed by is_configured
        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Accept": "text/event-stream",
            **self._extra_headers,
        }
        finish_reason: str | None = None
        usage: dict[str, int] = {}
        model_used = self.model
        try:
            async with self._http.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                json=self._payload(request),
                headers=headers,
                timeout=self._timeout,
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread())[:_MAX_ERROR_BODY].decode("utf-8", "replace")
                    raise classify_http_status(
                        resp.status_code, body, parse_retry_after(resp.headers.get("retry-after"))
                    )
                # Routers such as FreeLLMAPI say which upstream model answered.
                routed = resp.headers.get("x-routed-via")
                if routed:
                    model_used = routed.strip()[:200]
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk, dict) and chunk.get("error"):
                        raise ProviderUnavailableError("Provider reported an error mid-stream")
                    if not routed:
                        model_used = chunk.get("model") or model_used
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices") or []:
                        text = (choice.get("delta") or {}).get("content")
                        if text:
                            yield TextDelta(text)
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
        except ProviderError:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ProviderOfflineError(f"{self.name}: cannot reach provider") from exc
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(f"{self.name}: provider timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"{self.name}: connection problem") from exc

        yield StreamEnd(
            finish_reason=finish_reason,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            model=model_used,
        )
