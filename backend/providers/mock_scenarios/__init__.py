"""Scripted scenarios for the mock provider.

These are hand-authored stand-ins for model output, used so the full pipeline can run
without API access. They are *not* autonomous reasoning: every investigation that uses
them is labelled ``simulated`` in the API, UI and reports. The experiments they contain
are nevertheless executed for real in the sandbox, and their patches are verified for
real; nothing about execution results is scripted.

Scenario conventions:
* ``match``: substring of the target test name that selects the scenario;
* ``hypotheses``: a HypothesisSet payload;
* ``experiment_rounds``: list of ExperimentPlan payloads, indexed by round;
* ``repairs``: list of PatchDraft payloads, indexed by repair attempt;
* ``one_shot_repair``: the PatchDraft returned for the Baseline A (direct repair) mode,
  authored as the model's "first idea" without experimental evidence.
"""

from __future__ import annotations

from typing import Any

from providers.mock_scenarios import (
    d1_lost_update,
    d2_duplicate_charge,
    d3_transaction_leak,
    d4_async_error,
    d5_terminal_status,
)

SCENARIOS: list[dict[str, Any]] = [
    d1_lost_update.SCENARIO,
    d2_duplicate_charge.SCENARIO,
    d3_transaction_leak.SCENARIO,
    d4_async_error.SCENARIO,
    d5_terminal_status.SCENARIO,
]


def find_scenario(target_test: str | None) -> dict[str, Any] | None:
    if not target_test:
        return None
    for scenario in SCENARIOS:
        if scenario["match"] in target_test:
            return scenario
    return None
