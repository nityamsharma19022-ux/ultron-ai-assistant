"""Build the provider list and router from settings."""

from __future__ import annotations

import httpx

from ultron_core.ai.cooldown import CooldownStore
from ultron_core.ai.providers.anthropic_provider import AnthropicProvider
from ultron_core.ai.providers.base import ChatProvider
from ultron_core.ai.providers.mock import DevMockProvider
from ultron_core.ai.providers.ollama import OllamaProvider
from ultron_core.ai.providers.openai_compat import OpenAICompatibleProvider
from ultron_core.ai.router import AIRouter
from ultron_core.ai.types import ProviderKind
from ultron_core.config import Settings

CLOUD_PROVIDER_NAMES = ("groq", "gemini", "openrouter", "custom", "anthropic")


def build_providers(settings: Settings, http: httpx.AsyncClient) -> list[ChatProvider]:
    common = {
        "http": http,
        "context_char_budget": settings.ai_cloud_context_chars,
        "connect_timeout": settings.ai_connect_timeout_seconds,
        "read_timeout": settings.ai_request_timeout_seconds,
    }
    providers: list[ChatProvider] = [
        OpenAICompatibleProvider(
            name="groq",
            base_url=settings.groq_base_url,
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            **common,
        ),
        OpenAICompatibleProvider(
            name="gemini",
            base_url=settings.gemini_base_url,
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            **common,
        ),
        OpenAICompatibleProvider(
            name="openrouter",
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            extra_headers={"X-Title": "ULTRON"},
            **common,
        ),
        OpenAICompatibleProvider(
            name="custom",
            base_url=settings.custom_ai_base_url,
            api_key=settings.custom_ai_api_key,
            model=settings.custom_ai_model,
            **common,
        ),
        AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            effort=settings.anthropic_effort,
            base_url=settings.anthropic_base_url,
            context_char_budget=settings.ai_cloud_context_chars,
            connect_timeout=settings.ai_connect_timeout_seconds,
            read_timeout=settings.ai_request_timeout_seconds,
        ),
        OllamaProvider(
            http=http,
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            context_char_budget=settings.ai_local_context_chars,
            connect_timeout=settings.ai_connect_timeout_seconds,
            # Local models can take a while to load on first use.
            read_timeout=max(settings.ai_request_timeout_seconds, 180.0),
            think=settings.ollama_think,
            num_ctx=settings.ollama_num_ctx,
            keep_alive=settings.ollama_keep_alive,
        ),
    ]
    if settings.ai_dev_mock != "off":
        providers.insert(0, DevMockProvider(ProviderKind(settings.ai_dev_mock)))
    return providers


def build_router(
    settings: Settings, providers: list[ChatProvider], cooldowns: CooldownStore
) -> AIRouter:
    order = settings.cloud_provider_order
    if settings.ai_dev_mock == "cloud":
        order = ["mock-cloud", *order]
    return AIRouter(providers, cooldowns, default_cloud_order=order)
