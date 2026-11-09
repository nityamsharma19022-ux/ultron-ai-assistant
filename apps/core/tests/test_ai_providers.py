"""Provider adapters against mocked HTTP: no network, no API keys, no cost."""

from __future__ import annotations

import json

import anthropic
import httpx
import httpx2
import pytest
from pydantic import SecretStr

from ultron_core.ai import errors
from ultron_core.ai.providers.anthropic_provider import FALLBACK_BETA, AnthropicProvider
from ultron_core.ai.providers.ollama import OllamaProvider, model_matches
from ultron_core.ai.providers.openai_compat import OpenAICompatibleProvider
from ultron_core.ai.types import ChatMessage, ChatRequest, StreamEnd, TextDelta

FAKE_KEY = "sk-test-NEVER-REAL-0123456789"
REQUEST = ChatRequest(
    messages=(ChatMessage("user", "hello"),), system="You are ULTRON.", max_output_tokens=256
)


async def collect(provider, request: ChatRequest = REQUEST):  # type: ignore[no-untyped-def]
    text, end = [], None
    async for event in provider.stream(request):
        if isinstance(event, TextDelta):
            text.append(event.text)
        elif isinstance(event, StreamEnd):
            end = event
    return "".join(text), end


# --- OpenAI-compatible (Groq / Gemini / OpenRouter / custom) ----------------------


def openai_provider(handler, *, key: str | None = FAKE_KEY, model: str | None = "m-1"):  # type: ignore[no-untyped-def]
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleProvider(
        name="groq",
        http=http,
        base_url="https://api.example.test/v1",
        api_key=SecretStr(key) if key else None,
        model=model,
        context_char_budget=10_000,
        connect_timeout=1,
        read_timeout=5,
    )


def sse_body(*chunks: dict) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


async def test_openai_compatible_streams_text_and_usage() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=sse_body(
                {"model": "m-1", "choices": [{"delta": {"content": "Hel"}}]},
                {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2}},
            ),
            headers={"content-type": "text/event-stream"},
        )

    text, end = await collect(openai_provider(handler))
    assert text == "Hello"
    assert (end.finish_reason, end.input_tokens, end.output_tokens) == ("stop", 7, 2)
    assert seen["auth"] == f"Bearer {FAKE_KEY}"
    assert seen["url"] == "https://api.example.test/v1/chat/completions"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "You are ULTRON."}
    assert seen["body"]["stream"] is True
    # Text only: the model is never offered tools it could use to act.
    assert "tools" not in seen["body"] and "functions" not in seen["body"]


@pytest.mark.parametrize(
    ("status", "body", "headers", "expected", "retry_after"),
    [
        (
            429,
            '{"error":{"message":"Rate limit reached","code":"rate_limit_exceeded"}}',
            {"retry-after": "12"},
            errors.ProviderRateLimitedError,
            12.0,
        ),
        (
            429,
            '{"error":{"message":"You exceeded your current quota","type":"insufficient_quota"}}',
            {},
            errors.ProviderQuotaExhaustedError,
            None,
        ),
        # Gemini: per-minute limit is a short rate limit, with retryDelay hint.
        (
            429,
            '[{"error":{"code":429,"status":"RESOURCE_EXHAUSTED","message":"quota exceeded",'
            '"details":[{"quotaId":"GenerateRequestsPerMinutePerProjectPerModel-FreeTier"},'
            '{"retryDelay":"33s"}]}}]',
            {},
            errors.ProviderRateLimitedError,
            33.0,
        ),
        # Gemini: daily quota is exhaustion.
        (
            429,
            '[{"error":{"status":"RESOURCE_EXHAUSTED","details":[{"quotaId":'
            '"GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}}]',
            {},
            errors.ProviderQuotaExhaustedError,
            None,
        ),
        (
            402,
            '{"error":{"message":"Insufficient credits"}}',
            {},
            errors.ProviderQuotaExhaustedError,
            None,
        ),
        (401, '{"error":{"message":"Invalid API Key"}}', {}, errors.ProviderAuthError, None),
        (503, "upstream overloaded", {}, errors.ProviderUnavailableError, None),
        (400, '{"error":{"message":"context too long"}}', {}, errors.ProviderRequestError, None),
    ],
)
async def test_openai_compatible_error_mapping(  # type: ignore[no-untyped-def]
    status, body, headers, expected, retry_after
) -> None:
    provider = openai_provider(lambda r: httpx.Response(status, text=body, headers=headers))
    with pytest.raises(errors.ProviderError) as err:
        await collect(provider)
    assert type(err.value) is expected
    assert err.value.retry_after == retry_after
    assert FAKE_KEY not in str(err.value)


async def test_openai_compatible_offline_marks_network_down() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name or service not known", request=request)

    with pytest.raises(errors.ProviderOfflineError) as err:
        await collect(openai_provider(handler))
    assert err.value.network_down is True


async def test_openai_compatible_without_key_is_not_configured() -> None:
    calls = []
    provider = openai_provider(lambda r: calls.append(r) or httpx.Response(200), key=None)
    assert provider.is_configured() is False
    assert provider.missing_configuration() == "missing API key"
    with pytest.raises(errors.ProviderNotConfiguredError):
        await collect(provider)
    assert calls == []  # never contacted the provider


# --- Ollama (local) ----------------------------------------------------------------


def ollama_provider(handler, model: str | None = "llama3.2"):  # type: ignore[no-untyped-def]
    return OllamaProvider(
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        base_url="http://ollama.test:11434",
        model=model,
        context_char_budget=8_000,
        connect_timeout=1,
        read_timeout=5,
    )


def tags(*names: str) -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": n} for n in names]})


async def test_ollama_available_only_when_model_installed() -> None:
    ok = await ollama_provider(lambda r: tags("llama3.2:latest", "qwen3:8b")).availability()
    assert ok.available is True

    missing = await ollama_provider(lambda r: tags("qwen3:8b")).availability()
    assert missing.available is False
    assert missing.reason == "local model 'llama3.2' is not installed"

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    not_running = await ollama_provider(down).availability()
    assert not_running.available is False
    assert "not running" in (not_running.reason or "")


async def test_ollama_without_model_is_not_configured() -> None:
    provider = ollama_provider(lambda r: tags("llama3.2"), model=None)
    assert provider.is_configured() is False
    assert (await provider.availability()).available is False


def test_ollama_model_name_matching() -> None:
    assert model_matches("llama3.2", "llama3.2:latest")
    assert model_matches("qwen3:8b", "qwen3:8b")
    assert not model_matches("qwen3:8b", "qwen3:latest")
    assert not model_matches("llama3.2", "llama3.2:1b")


async def test_ollama_streams_ndjson() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        lines = [
            {"message": {"role": "assistant", "content": "Off"}, "done": False},
            {"message": {"role": "assistant", "content": "line"}, "done": False},
            {
                "message": {"content": ""},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 20,
                "eval_count": 2,
                "model": "llama3.2",
            },
        ]
        return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())

    text, end = await collect(ollama_provider(handler))
    assert text == "Offline"
    assert (end.input_tokens, end.output_tokens, end.finish_reason) == (20, 2, "stop")
    assert seen["body"]["messages"][0]["role"] == "system"
    assert "tools" not in seen["body"]


async def test_ollama_missing_model_error() -> None:
    provider = ollama_provider(lambda r: httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(errors.ModelNotInstalledError):
        await collect(provider)


async def test_ollama_not_running_error() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(errors.ProviderUnavailableError) as err:
        await collect(ollama_provider(down))
    assert err.value.network_down is False  # local runtime down != internet down


# --- Anthropic (official SDK, mocked transport) ----------------------------------------


def anthropic_events(*texts: str, stop_reason: str = "end_turn") -> bytes:
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-opus-5-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 12, "output_tokens": 1},
                },
            },
        ),
    ]
    if texts:
        events.append(
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            )
        )
        for t in texts:
            events.append(
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": t},
                    },
                )
            )
        events.append(("content_block_stop", {"type": "content_block_stop", "index": 0}))
    events += [
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 5},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events).encode()


def anthropic_provider(handler, key: str | None = FAKE_KEY) -> AnthropicProvider:  # type: ignore[no-untyped-def]
    return AnthropicProvider(
        api_key=SecretStr(key) if key else None,
        model="claude-opus-5-5",
        max_tokens=16_000,
        effort=None,
        context_char_budget=100_000,
        connect_timeout=1,
        read_timeout=5,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )


async def test_anthropic_streams_with_refusal_fallback_enabled() -> None:
    seen = {}

    def handler(request):  # type: ignore[no-untyped-def]
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            content=anthropic_events("Hi ", "there"),
            headers={"content-type": "text/event-stream"},
        )

    text, end = await collect(anthropic_provider(handler))
    assert text == "Hi there"
    assert (end.finish_reason, end.input_tokens, end.output_tokens) == ("end_turn", 12, 5)
    body = seen["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["system"] == "You are ULTRON."
    assert body["fallbacks"] == "default"
    assert FALLBACK_BETA in seen["headers"]["anthropic-beta"]
    assert seen["headers"]["authorization"] == f"Bearer {FAKE_KEY}"
    assert "tools" not in body


@pytest.mark.parametrize(
    ("status", "error_type", "message", "expected"),
    [
        (429, "rate_limit_error", "rate limited", errors.ProviderRateLimitedError),
        (529, "overloaded_error", "overloaded", errors.ProviderUnavailableError),
        (401, "authentication_error", "invalid x-api-key", errors.ProviderAuthError),
        (
            400,
            "invalid_request_error",
            "Your credit balance is too low",
            errors.ProviderQuotaExhaustedError,
        ),
        (400, "invalid_request_error", "messages: bad", errors.ProviderRequestError),
    ],
)
async def test_anthropic_error_mapping(status, error_type, message, expected) -> None:  # type: ignore[no-untyped-def]
    def handler(request):  # type: ignore[no-untyped-def]
        return httpx2.Response(
            status, json={"type": "error", "error": {"type": error_type, "message": message}}
        )

    with pytest.raises(errors.ProviderError) as err:
        await collect(anthropic_provider(handler))
    assert type(err.value) is expected
    assert FAKE_KEY not in str(err.value)


async def test_anthropic_refusal_before_output_is_reported() -> None:
    def handler(request):  # type: ignore[no-untyped-def]
        return httpx2.Response(
            200,
            content=anthropic_events(stop_reason="refusal"),
            headers={"content-type": "text/event-stream"},
        )

    with pytest.raises(errors.ProviderRefusalError):
        await collect(anthropic_provider(handler))


async def test_anthropic_without_key_is_not_configured() -> None:
    provider = anthropic_provider(lambda r: httpx2.Response(500), key=None)
    assert provider.is_configured() is False
    with pytest.raises(errors.ProviderNotConfiguredError):
        await collect(provider)


# --- Ollama: thinking models (e.g. Qwen 3.5), context size, empty answers -----------


async def test_ollama_sends_think_and_context_settings() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        done = {"message": {"content": "ok"}, "done": True, "done_reason": "stop"}
        return httpx.Response(200, content=json.dumps(done).encode())

    provider = OllamaProvider(
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        base_url="http://ollama.test:11434",
        model="qwen3.5:4b",
        context_char_budget=16_000,
        connect_timeout=1,
        read_timeout=5,
        think="false",
        num_ctx=8192,
        keep_alive="10m",
    )
    await collect(provider)
    body = seen["body"]
    assert body["model"] == "qwen3.5:4b"
    assert body["think"] is False
    assert body["options"] == {"num_predict": 256, "num_ctx": 8192}
    assert body["keep_alive"] == "10m"


@pytest.mark.parametrize(("setting", "expected"), [("true", True), ("high", "high")])
async def test_ollama_think_levels(setting, expected) -> None:  # type: ignore[no-untyped-def]
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b'{"message":{"content":"x"},"done":true}')

    provider = ollama_provider(handler)
    provider._think = __import__("ultron_core.ai.providers.ollama", fromlist=["x"]).think_value(
        setting
    )
    await collect(provider)
    assert seen["body"]["think"] == expected


async def test_ollama_default_think_setting_omits_the_field() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b'{"message":{"content":"x"},"done":true}')

    provider = OllamaProvider(
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        base_url="http://o.test",
        model="m",
        context_char_budget=1000,
        connect_timeout=1,
        read_timeout=5,
        think="default",
        num_ctx=None,
    )
    await collect(provider)
    assert "think" not in seen["body"]
    assert "num_ctx" not in seen["body"]["options"]


async def test_ollama_reasoning_field_is_never_shown() -> None:
    lines = [
        {"message": {"role": "assistant", "content": "", "thinking": "secret plan"}, "done": False},
        {"message": {"content": "", "thinking": " more"}, "done": False},
        {"message": {"content": "Answer"}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": "stop"},
    ]
    body = "\n".join(json.dumps(x) for x in lines).encode()
    text, _ = await collect(ollama_provider(lambda r: httpx.Response(200, content=body)))
    assert text == "Answer"


@pytest.mark.parametrize(
    "chunks",
    [
        ["<think>plan", " more</think>", "\n\nHello", " there"],
        ["<th", "ink>plan</th", "ink>Hello there"],
        ["  <think>", "x</think>Hello there"],
    ],
)
async def test_ollama_inline_think_tags_are_removed(chunks) -> None:  # type: ignore[no-untyped-def]
    lines = [{"message": {"content": c}, "done": False} for c in chunks]
    lines.append({"message": {"content": ""}, "done": True})
    body = "\n".join(json.dumps(x) for x in lines).encode()
    text, _ = await collect(ollama_provider(lambda r: httpx.Response(200, content=body)))
    assert text == "Hello there"


async def test_ollama_text_starting_with_angle_bracket_is_kept() -> None:
    lines = [{"message": {"content": "<b>bold</b> text"}, "done": False}, {"done": True}]
    body = "\n".join(json.dumps(x) for x in lines).encode()
    text, _ = await collect(ollama_provider(lambda r: httpx.Response(200, content=body)))
    assert text == "<b>bold</b> text"


async def test_ollama_only_thinking_then_length_limit_is_an_error() -> None:
    lines = [
        {"message": {"content": "", "thinking": "long reasoning"}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": "length"},
    ]
    body = "\n".join(json.dumps(x) for x in lines).encode()
    with pytest.raises(errors.ProviderUnavailableError) as err:
        await collect(ollama_provider(lambda r: httpx.Response(200, content=body)))
    assert "output limit" in err.value.message


async def test_ollama_real_runtime_404_body_maps_to_model_not_installed() -> None:
    # Exact body returned by Ollama 0.40.15 for a model that isn't pulled.
    provider = ollama_provider(
        lambda r: httpx.Response(404, json={"error": "model 'qwen3.5:4b' not found"})
    )
    with pytest.raises(errors.ModelNotInstalledError) as err:
        await collect(provider)
    assert "is not installed" in err.value.message


async def test_ollama_think_not_supported_is_a_clear_request_error() -> None:
    provider = ollama_provider(
        lambda r: httpx.Response(400, json={"error": '"m" does not support thinking'})
    )
    with pytest.raises(errors.ProviderRequestError) as err:
        await collect(provider)
    assert "ULTRON_OLLAMA_THINK" in err.value.message
