"""Structured logging output and secret redaction."""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from ultron_core.logging_setup import configure_logging, get_logger


@pytest.fixture(autouse=True)
def _reset_structlog():
    yield
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def _json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


def test_json_logs_are_structured(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "json")
    structlog.contextvars.bind_contextvars(request_id="abc123")
    get_logger("ultron.test").info("unit.event", answer=42)
    line = _json_lines(capfd.readouterr().err)[-1]
    assert line["event"] == "unit.event"
    assert line["answer"] == 42
    assert line["level"] == "info"
    assert line["request_id"] == "abc123"
    assert "timestamp" in line


def test_stdlib_logs_use_the_same_format(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "json")
    logging.getLogger("third.party").warning("hello from stdlib")
    line = _json_lines(capfd.readouterr().err)[-1]
    assert line["event"] == "hello from stdlib"
    assert line["level"] == "warning"


def test_secrets_are_redacted(capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "json")
    get_logger().info("oops", password="hunter2-secret", refresh_token="rt-value")
    out = capfd.readouterr().err
    assert "hunter2-secret" not in out
    assert "rt-value" not in out
