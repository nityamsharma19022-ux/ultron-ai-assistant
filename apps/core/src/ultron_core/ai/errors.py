"""Error categories every adapter maps provider failures into.

The router decides what to do from the category, never from provider
specific details. Messages here are safe to show to clients: they never
contain upstream response bodies, URLs or credentials.
"""

from __future__ import annotations

import re


class ProviderError(Exception):
    code = "provider_error"
    # Whether trying the next provider makes sense.
    fallback_allowed = True
    # Default cooldown (seconds) during which the router skips this provider.
    cooldown_seconds = 0.0
    # True when the failure suggests the whole network is down (offline).
    network_down = False

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after

    @property
    def effective_cooldown(self) -> float:
        return self.retry_after if self.retry_after is not None else self.cooldown_seconds


class ProviderNotConfiguredError(ProviderError):
    code = "not_configured"


class ProviderAuthError(ProviderError):
    """Missing/invalid/revoked API key or no permission."""

    code = "auth_failed"
    cooldown_seconds = 600.0


class ProviderRateLimitedError(ProviderError):
    code = "rate_limited"
    cooldown_seconds = 60.0


class ProviderQuotaExhaustedError(ProviderError):
    """Free-tier quota used up, or no credit left."""

    code = "quota_exhausted"
    cooldown_seconds = 3600.0


class ProviderUnavailableError(ProviderError):
    """Server error, overload or timeout at the provider."""

    code = "unavailable"
    cooldown_seconds = 30.0


class ProviderOfflineError(ProviderUnavailableError):
    """Could not reach the provider at all (DNS / connection failure)."""

    code = "offline"
    cooldown_seconds = 15.0
    network_down = True


class ModelNotInstalledError(ProviderUnavailableError):
    code = "model_not_installed"
    cooldown_seconds = 15.0


class ProviderRequestError(ProviderError):
    """The request itself was rejected (bad parameters, too long)."""

    code = "invalid_request"
    fallback_allowed = False


class ProviderRefusalError(ProviderError):
    """The model declined to answer (safety refusal)."""

    code = "refused"
    fallback_allowed = False


_PER_MINUTE_MARKERS = ("perminute", "per minute", "per_minute", "rpm", "tpm", "tokens per minute")
_QUOTA_MARKERS = (
    "insufficient_quota",
    "exceeded your current quota",
    "quota",
    "resource_exhausted",
    "credit",
    "billing",
    "perday",
    "per day",
)
_RETRY_DELAY = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')


def classify_http_status(status: int, body_text: str, retry_after: float | None) -> ProviderError:
    """Map an HTTP error from an OpenAI-compatible or similar API.

    Short per-minute limits become ``rate_limited`` (short cooldown); daily
    or credit exhaustion becomes ``quota_exhausted`` (long cooldown).
    """
    lowered = body_text.lower()
    if retry_after is None:
        match = _RETRY_DELAY.search(body_text)
        if match:
            retry_after = parse_retry_after(match.group(1))
    if status == 402:
        return ProviderQuotaExhaustedError("Provider quota or credit exhausted")
    if status == 429:
        if any(m in lowered for m in _PER_MINUTE_MARKERS):
            return ProviderRateLimitedError("Provider rate limit reached", retry_after=retry_after)
        if any(m in lowered for m in _QUOTA_MARKERS):
            return ProviderQuotaExhaustedError("Provider quota exhausted", retry_after=retry_after)
        return ProviderRateLimitedError("Provider rate limit reached", retry_after=retry_after)
    if status in (401, 403):
        return ProviderAuthError("Provider rejected the API key")
    if status == 404:
        return ProviderRequestError("Provider does not know the configured model")
    if status in (400, 413, 422):
        return ProviderRequestError("Provider rejected the request")
    if status in (408, 504):
        return ProviderUnavailableError("Provider timed out")
    return ProviderUnavailableError(f"Provider error (HTTP {status})")


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if 0 <= seconds <= 86_400 else None
