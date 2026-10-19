"""Shared runtime for agents: budgets, events, audited model calls."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.config import get_settings
from core.database import session_scope
from core.models import Event, Investigation, ModelCall
from core.schemas import InvestigationReport
from providers.base import AgentRequest, AIProvider, ProviderError, T, Usage
from sandbox.docker import DockerSandbox
from services.workspace import WorkspaceManager

log = logging.getLogger(__name__)

AGENT_LABELS = {
    "orchestrator": "G · Orchestrator",
    "investigator": "A · Repository Investigator",
    "hypothesis_generator": "B · Hypothesis Generator",
    "experiment_designer": "C · Experiment Designer",
    "experiment_executor": "D · Experiment Executor",
    "repair_engineer": "E · Repair Engineer",
    "verifier": "F · Independent Verifier",
}


class BudgetExceededError(RuntimeError):
    pass


class InvestigationCancelledError(RuntimeError):
    pass


class AgentError(RuntimeError):
    pass


@dataclass
class Budget:
    max_model_calls: int
    max_experiments: int
    max_repair_attempts: int
    max_experiment_rounds: int
    time_budget_s: int
    price_input_per_m: float
    price_output_per_m: float
    price_cached_input_per_m: float = 0.0
    model_calls: int = 0
    experiments: int = 0
    sandbox_runs: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    failed_calls: int = 0
    tokens_estimated: bool = False
    started: float = field(default_factory=time.monotonic)

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started

    def check_time(self) -> None:
        if self.elapsed_s() > self.time_budget_s:
            raise BudgetExceededError(f"Time budget of {self.time_budget_s}s exhausted")

    def check_model_call(self) -> None:
        self.check_time()
        if self.model_calls >= self.max_model_calls:
            raise BudgetExceededError(f"Model call budget of {self.max_model_calls} exhausted")

    def experiments_remaining(self) -> int:
        return max(0, self.max_experiments - self.experiments)

    def record(self, usage: Usage) -> None:
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        self.cached_tokens += usage.cached_tokens
        self.reasoning_tokens += usage.reasoning_tokens
        self.tokens_estimated = self.tokens_estimated or usage.estimated

    @property
    def estimated_cost_usd(self) -> float:
        # Cached prompt tokens are billed at the cached-input rate; reasoning tokens are already
        # part of completion_tokens (Meta CompletionUsage schema).
        cached = min(self.cached_tokens, self.prompt_tokens)
        return round(
            (self.prompt_tokens - cached) / 1e6 * self.price_input_per_m
            + cached / 1e6 * self.price_cached_input_per_m
            + self.completion_tokens / 1e6 * self.price_output_per_m,
            6,
        )

    def limits(self) -> dict[str, Any]:
        return {
            "max_model_calls": self.max_model_calls,
            "max_experiments": self.max_experiments,
            "max_repair_attempts": self.max_repair_attempts,
            "max_experiment_rounds": self.max_experiment_rounds,
            "time_budget_s": self.time_budget_s,
        }

    def usage(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "experiments": self.experiments,
            "sandbox_runs": self.sandbox_runs,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "failed_model_calls": self.failed_calls,
            "tokens_estimated": self.tokens_estimated,
            "estimated_cost_usd": self.estimated_cost_usd,
            "pricing": {
                "input_per_m": self.price_input_per_m,
                "cached_input_per_m": self.price_cached_input_per_m,
                "output_per_m": self.price_output_per_m,
            },
            "elapsed_s": round(self.elapsed_s(), 2),
        }


@dataclass
class InvestigationContext:
    investigation_id: str
    repository_name: str
    snapshot: Path
    mode: str
    symptom: str
    target_test: str | None
    provider: AIProvider
    sandbox: DockerSandbox
    workspaces: WorkspaceManager
    budget: Budget
    report: InvestigationReport | None = None
    workspaces_keep: bool = False

    # -- events ----------------------------------------------------------------
    def emit(self, agent: str, type_: str, message: str, data: dict[str, Any] | None = None) -> None:
        with session_scope() as db:
            db.add(
                Event(
                    investigation_id=self.investigation_id,
                    agent=agent,
                    type=type_,
                    message=message,
                    data=data or {},
                )
            )
        log.info(message, extra={"investigation": self.investigation_id, "agent": agent, "event": type_})

    def set_phase(self, phase: str, agent: str | None) -> None:
        with session_scope() as db:
            inv = db.get(Investigation, self.investigation_id)
            if inv is None:
                raise InvestigationCancelledError("Investigation was deleted")
            if inv.status == "cancelling":
                raise InvestigationCancelledError("Cancelled by user")
            inv.phase = phase
            inv.active_agent = agent
            inv.usage = self.budget.usage()
        if agent:
            self.emit(
                agent, "agent_started", f"{AGENT_LABELS.get(agent, agent)} started: {phase}", {"phase": phase}
            )

    def checkpoint(self) -> None:
        self.budget.check_time()
        with session_scope() as db:
            inv = db.get(Investigation, self.investigation_id)
            if inv is None or inv.status == "cancelling":
                raise InvestigationCancelledError("Cancelled by user")
            inv.usage = self.budget.usage()

    # -- model calls -------------------------------------------------------------
    def call_model(
        self,
        *,
        agent: str,
        task: str,
        system: str,
        user: str,
        context: dict[str, Any],
        schema: type[T],
    ) -> T:
        self.budget.check_model_call()
        self.checkpoint()
        request = AgentRequest(agent=agent, task=task, system=system, user=user, context=context)
        provider = self.provider
        self.budget.model_calls += 1
        try:
            completion = provider.generate(request, schema)
        except (ProviderError, ValueError) as exc:
            # Tokens consumed before the failure (e.g. output that failed validation) were billed.
            spent = getattr(exc, "usage", None) or Usage()
            self.budget.record(spent)
            self.budget.failed_calls += 1
            with session_scope() as db:
                db.add(
                    ModelCall(
                        investigation_id=self.investigation_id,
                        agent=agent,
                        task=task,
                        provider=provider.name,
                        model=provider.model,
                        simulated=provider.simulated,
                        ok=False,
                        error=str(exc)[:2000],
                        prompt_tokens=spent.prompt_tokens,
                        completion_tokens=spent.completion_tokens,
                        cached_tokens=spent.cached_tokens,
                        reasoning_tokens=spent.reasoning_tokens,
                        tokens_estimated=spent.estimated,
                        latency_ms=spent.latency_ms,
                    )
                )
            self.emit(
                agent,
                "model_error",
                f"Model call failed ({task}): {str(exc)[:300]}",
                {
                    "task": task,
                    "prompt_tokens": spent.prompt_tokens,
                    "completion_tokens": spent.completion_tokens,
                },
            )
            raise AgentError(f"Model call for {task} failed: {exc}") from exc
        usage = completion.usage
        self.budget.record(usage)
        with session_scope() as db:
            db.add(
                ModelCall(
                    investigation_id=self.investigation_id,
                    agent=agent,
                    task=task,
                    provider=completion.provider,
                    model=completion.model,
                    simulated=completion.simulated,
                    ok=True,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cached_tokens=usage.cached_tokens,
                    reasoning_tokens=usage.reasoning_tokens,
                    tokens_estimated=usage.estimated,
                    latency_ms=usage.latency_ms,
                )
            )
        label = (
            "scripted mock response" if completion.simulated else f"{completion.provider}/{completion.model}"
        )
        self.emit(
            agent,
            "model_call",
            f"{task}: {label} ({usage.prompt_tokens}+{usage.completion_tokens} tokens"
            f"{', estimated' if usage.estimated else ''})",
            {
                "task": task,
                "provider": completion.provider,
                "model": completion.model,
                "simulated": completion.simulated,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "cached_tokens": usage.cached_tokens,
                "reasoning_tokens": usage.reasoning_tokens,
                "tokens_estimated": usage.estimated,
                "latency_ms": usage.latency_ms,
            },
        )
        return completion.output


def build_budget(config: Any) -> Budget:
    settings = get_settings()
    return Budget(
        max_model_calls=config.max_model_calls,
        max_experiments=config.max_experiments,
        max_repair_attempts=config.max_repair_attempts,
        max_experiment_rounds=config.max_experiment_rounds,
        time_budget_s=config.time_budget_s,
        price_input_per_m=settings.ai_price_input_per_m,
        price_output_per_m=settings.ai_price_output_per_m,
        price_cached_input_per_m=settings.ai_price_cached_input_per_m,
    )


def dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
