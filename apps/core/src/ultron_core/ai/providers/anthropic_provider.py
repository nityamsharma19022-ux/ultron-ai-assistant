"""Adapter for Anthropic Claude (optional, paid) using the official SDK."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anthropic
from pydantic import SecretStr

from ultron_core.ai.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderOfflineError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
    ProviderRefusalError,
    ProviderRequestError,
    ProviderUnavailableError,
    classify_http_status,
    parse_retry_after,
)
from ultron_core.ai.providers.base import ChatProvider
from ultron_core.ai.types import ChatRequest, ProviderKind, StreamEnd, StreamEvent, TextDelta

# Server-side refusal fallback: if Claude declines, the API retries on the
# model Anthropic recommends for that refusal category, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _merge_same_role(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    for m in messages:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1] = {
                "role": m["role"],
                "content": merged[-1]["content"] + "\n\n" + m["content"],
            }
        else:
            merged.append(dict(m))
    return merged


class AnthropicProvider(ChatProvider):
    kind = ProviderKind.CLOUD

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        model: str | None,
        max_tokens: int,
        effort: str | None,
        context_char_budget: int,
        connect_timeout: float,
        read_timeout: float,
        base_url: str | None = None,
        http_client: Any | None = None,
        name: str = "anthropic",
    ) -> None:
        self.name = name
        self.model = model
        self.context_char_budget = context_char_budget
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._effort = effort
        self._client: anthropic.AsyncAnthropic | None = None
        if self.is_configured():
            assert api_key is not None  # noqa: S101
            kwargs: dict[str, Any] = {
                "api_key": api_key.get_secret_value(),
                # The router does failover itself; SDK retries would only delay it.
                "max_retries": 0,
                "timeout": anthropic.Timeout(read_timeout, connect=connect_timeout),
            }
            if base_url:
                kwargs["base_url"] = base_url
            if http_client is not None:
                kwargs["http_client"] = http_client
            self._client = anthropic.AsyncAnthropic(**kwargs)

    def is_configured(self) -> bool:
        return bool(
            self.model and self._api_key is not None and self._api_key.get_secret_value().strip()
        )

    def missing_configuration(self) -> str | None:
        if self._api_key is None or not self._api_key.get_secret_value().strip():
            return "missing API key"
        if not self.model:
            return "missing model"
        return None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()

    def _params(self, request: ChatRequest) -> dict[str, Any]:
        messages = _merge_same_role(
            [{"role": m.role, "content": m.content} for m in request.messages if m.role != "system"]
        )
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_tokens,
            "system": request.system,
            "messages": messages,
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
            # No "tools": replies are text only.
        }
        if self._effort:
            params["output_config"] = {"effort": self._effort}
        return params

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if self._client is None or not self.is_configured():
            raise ProviderNotConfiguredError(f"{self.name}: {self.missing_configuration()}")
        emitted = False
        try:
            async with self._client.beta.messages.stream(**self._params(request)) as stream:
                async for text in stream.text_stream:
                    if text:
                        emitted = True
                        yield TextDelta(text)
                final = await stream.get_final_message()
        except ProviderError:
            raise
        except anthropic.APIConnectionError as exc:
            if isinstance(exc, anthropic.APITimeoutError):
                raise ProviderUnavailableError(f"{self.name}: provider timed out") from exc
            raise ProviderOfflineError(f"{self.name}: cannot reach provider") from exc
        except anthropic.APIStatusError as exc:
            raise _map_status_error(exc) from exc

        if final.stop_reason == "refusal" and not emitted:
            raise ProviderRefusalError("The model declined to answer this request")
        yield StreamEnd(
            finish_reason=final.stop_reason,
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
            model=final.model,
        )


def _map_status_error(exc: anthropic.APIStatusError) -> ProviderError:
    retry_after = parse_retry_after(exc.response.headers.get("retry-after"))
    message = str(exc).lower()
    # Spend-limit errors subclass RateLimitError in the SDK, so check them first.
    if isinstance(exc, anthropic.EnforcedSpendLimitReachedError) or exc.status_code == 402:
        return ProviderQuotaExhaustedError("Provider spend limit or credit exhausted")
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderRateLimitedError("Provider rate limit reached", retry_after=retry_after)
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ProviderAuthError("Provider rejected the API key")
    if isinstance(exc, anthropic.BadRequestError):
        if "credit balance" in message:
            return ProviderQuotaExhaustedError("Provider credit exhausted")
        return ProviderRequestError("Provider rejected the request")
    if isinstance(exc, anthropic.NotFoundError):
        return ProviderRequestError("Provider does not know the configured model")
    if isinstance(
        exc,
        (
            anthropic.OverloadedError,
            anthropic.InternalServerError,
            anthropic.ServiceUnavailableError,
        ),
    ):
        return ProviderUnavailableError("Provider is overloaded or unavailable")
    return classify_http_status(exc.status_code, "", retry_after)
