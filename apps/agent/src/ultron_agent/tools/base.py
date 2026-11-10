"""Shared tool types."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class ToolError(Exception):
    """A tool failed; ``retryable`` failures may be tried again by Core."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


class Cancelled(Exception):
    """The user cancelled the task while the step was running."""


@dataclass
class ToolContext:
    config: Any  # AgentConfig
    progress: Callable[[str], bool]  # report progress; returns True if cancelled

    def check(self, message: str) -> None:
        if self.progress(message):
            raise Cancelled
