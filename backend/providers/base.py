"""Provider-independent model interface."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status: int | None = None,
        usage: Usage | None = None,
        retry_after_s: float | None = None,
        param: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        # Tokens already consumed (and billed) before the failure, so callers can account for them.
        self.usage = usage
        self.retry_after_s = retry_after_s
        self.param = param


@dataclass
class AgentRequest:
    """A single structured request from an agent.

    `system`/`user` are the rendered prompts sent to real models. `context` carries the
    structured facts the prompts were rendered from; the mock provider uses it to select
    scripted fixtures, real providers ignore it.
    """

    agent: str
    task: str
    system: str
    user: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated: bool = False
    latency_ms: int = 0
    cached_tokens: int = 0  # subset of prompt_tokens served from the prompt cache
    reasoning_tokens: int = 0  # subset of completion_tokens spent on reasoning
    requests: int = 0  # HTTP requests that returned a completion

    def add(self, raw: dict[str, Any] | None) -> None:
        """Accumulates an OpenAI-style `usage` object (Meta CompletionUsage schema)."""
        raw = raw or {}
        self.prompt_tokens += int(raw.get("prompt_tokens") or 0)
        self.completion_tokens += int(raw.get("completion_tokens") or 0)
        self.cached_tokens += int((raw.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        self.reasoning_tokens += int(
            (raw.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
        )
        self.requests += 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class Completion[T: BaseModel]:
    output: T
    usage: Usage
    provider: str
    model: str
    simulated: bool
    raw_text: str = ""


class AIProvider(ABC):
    name: str
    model: str
    simulated: bool = False

    @abstractmethod
    def generate(self, request: AgentRequest, schema: type[T]) -> Completion[T]: ...

    @abstractmethod
    def check(self, deep: bool = False) -> dict[str, Any]: ...

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "simulated": self.simulated}


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def extract_json(text: str) -> Any:
    """Parses JSON from a model reply, tolerating code fences and leading prose."""
    text = text.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
