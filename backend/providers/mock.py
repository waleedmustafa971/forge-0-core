"""Deterministic mock provider.

Returns scripted fixtures (see :mod:`providers.mock_scenarios`) so the full pipeline can be
exercised without API access. Every completion is flagged ``simulated=True`` and token
counts are flagged as estimates. When no scenario matches, the mock returns a generic,
explicitly non-diagnostic response and proposes no patch, rather than inventing one.
"""

from __future__ import annotations

import json
import time
from typing import Any

from providers.base import AgentRequest, AIProvider, Completion, ProviderError, T, Usage, estimate_tokens
from providers.mock_scenarios import find_scenario


def _generic(task: str, context: dict[str, Any]) -> dict[str, Any]:
    target = context.get("target_test") or "the failing test"
    files = context.get("implicated_files") or []
    location = files[0] if files else "the code under test"
    if task == "hypotheses":
        return {
            "reasoning_summary": (
                "[mock] No scripted scenario matches this failure. These placeholder hypotheses are derived "
                "mechanically from the failure location and are not a diagnosis."
            ),
            "hypotheses": [
                {
                    "key": "H1",
                    "title": f"Defect in {location}",
                    "explanation": f"The top implicated frame for '{target}' is in {location}.",
                    "suspected_locations": files[:3],
                    "supporting_evidence": [str(context.get("error") or "")[:200]],
                    "contradicting_evidence": [],
                    "prior": 0.5,
                },
                {
                    "key": "H2",
                    "title": "Defect in test setup or fixtures",
                    "explanation": "The failure could originate in shared test helpers rather than "
                    "product code.",
                    "suspected_locations": [],
                    "supporting_evidence": [],
                    "contradicting_evidence": [],
                    "prior": 0.3,
                },
            ],
        }
    if task == "experiments":
        return {
            "rationale": "[mock] No scripted experiments for this failure; "
            "no further experiment is proposed.",
            "experiments": [],
            "conclude": True,
        }
    if task in ("repair", "one_shot_repair"):
        return {
            "hypothesis": "H1",
            "summary": "[mock] No scripted repair available",
            "rationale": "The mock provider has no scenario for this failure and does not fabricate patches.",
            "edits": [],
            "risk_notes": [],
        }
    raise ProviderError(f"mock provider does not support task {task!r}")


class MockProvider(AIProvider):
    name = "mock"
    simulated = True

    def __init__(self, model: str = "mock-scripted-v1") -> None:
        self.model = model

    def _payload(self, request: AgentRequest) -> dict[str, Any]:
        ctx = request.context
        scenario = find_scenario(ctx.get("target_test"))
        if scenario is None:
            return _generic(request.task, ctx)
        if request.task == "hypotheses":
            return scenario["hypotheses"]
        if request.task == "experiments":
            rounds = scenario["experiment_rounds"]
            index = int(ctx.get("round", 0))
            if index < len(rounds):
                return rounds[index]
            return {
                "rationale": "[mock] The scripted scenario has no further experiments.",
                "experiments": [],
                "conclude": True,
            }
        if request.task == "repair":
            repairs = scenario["repairs"]
            attempt = int(ctx.get("attempt", 0))
            if attempt < len(repairs):
                return repairs[attempt]
            return {
                "hypothesis": repairs[-1]["hypothesis"],
                "summary": "[mock] No further scripted repair attempts",
                "rationale": "The scripted scenario has no additional repair attempts.",
                "edits": [],
                "risk_notes": [],
            }
        if request.task == "one_shot_repair":
            return scenario["one_shot_repair"]
        raise ProviderError(f"mock provider does not support task {request.task!r}")

    def generate(self, request: AgentRequest, schema: type[T]) -> Completion[T]:
        started = time.monotonic()
        payload = self._payload(request)
        text = json.dumps(payload)
        output = schema.model_validate(payload)
        usage = Usage(
            prompt_tokens=estimate_tokens(request.system) + estimate_tokens(request.user),
            completion_tokens=estimate_tokens(text),
            estimated=True,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return Completion(output, usage, self.name, self.model, True, text)

    def check(self, deep: bool = False) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "ok": True,
            "simulated": True,
            "detail": "Mock provider: scripted fixtures, no network access, no real inference.",
        }
