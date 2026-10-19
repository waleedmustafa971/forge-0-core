"""Hypothesis ranking under experimental evidence.

Hypotheses are treated as competing explanations plus an explicit "unexplained" bucket
(so that refuting every proposed hypothesis does not inflate a weak survivor). Each
executed experiment is scored against the predictions made *before* it ran:

* prediction matched the observation   -> likelihood 0.9
* prediction contradicted it           -> likelihood 0.1
* no prediction for this hypothesis    -> likelihood 0.5 (uninformative)

Posteriors are renormalised after every experiment. Errors and timeouts carry no
evidence and leave the ranking unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

L_MATCH = 0.9
L_MISMATCH = 0.1
L_NONE = 0.5
OTHER_PRIOR = 0.1
CONFIRM_THRESHOLD = 0.75
REFUTE_THRESHOLD = 0.1


@dataclass
class HypothesisBelief:
    key: str
    confidence: float
    support: int = 0
    contradictions: int = 0
    discriminating_support: int = 0
    status: str = "open"
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BeliefState:
    hypotheses: dict[str, HypothesisBelief]
    other: float

    def ranked(self) -> list[HypothesisBelief]:
        return sorted(self.hypotheses.values(), key=lambda h: h.confidence, reverse=True)

    def leader(self) -> HypothesisBelief | None:
        ranked = self.ranked()
        return ranked[0] if ranked else None

    @property
    def decisive(self) -> bool:
        return any(h.status == "confirmed" for h in self.hypotheses.values())

    def snapshot(self) -> dict[str, Any]:
        return {
            "hypotheses": {k: round(h.confidence, 4) for k, h in self.hypotheses.items()},
            "unexplained": round(self.other, 4),
        }


def initial_state(priors: dict[str, float]) -> BeliefState:
    cleaned = {k: max(0.01, min(1.0, float(v))) for k, v in priors.items()}
    total = sum(cleaned.values()) or 1.0
    scale = (1.0 - OTHER_PRIOR) / total
    hyps = {k: HypothesisBelief(key=k, confidence=v * scale) for k, v in cleaned.items()}
    return BeliefState(hyps, OTHER_PRIOR)


def prediction_matches(prediction: dict[str, Any], outcome: str, output: str) -> tuple[bool, str]:
    expected = prediction.get("outcome")
    if expected != outcome:
        return False, f"predicted {expected}, observed {outcome}"
    needle = prediction.get("output_contains")
    if needle:
        if needle.lower() in output.lower():
            return True, f"observed {outcome} with expected output {needle!r}"
        return False, f"observed {outcome} but output lacked {needle!r}"
    return True, f"predicted and observed {outcome}"


def is_discriminating(predictions: list[dict[str, Any]]) -> bool:
    signatures = {(p.get("outcome"), p.get("output_contains") or "") for p in predictions}
    return len(signatures) > 1


def evaluate(predictions: list[dict[str, Any]], outcome: str, output: str) -> list[dict[str, Any]]:
    results = []
    for prediction in predictions:
        matched, reason = prediction_matches(prediction, outcome, output)
        results.append(
            {
                "hypothesis": prediction.get("hypothesis"),
                "predicted": prediction.get("outcome"),
                "output_contains": prediction.get("output_contains"),
                "observed": outcome,
                "matched": matched,
                "reason": reason,
            }
        )
    return results


def apply_evidence(
    state: BeliefState,
    experiment_key: str,
    evaluations: list[dict[str, Any]],
    discriminating: bool,
) -> BeliefState:
    by_key = {e["hypothesis"]: e for e in evaluations}
    weighted: dict[str, float] = {}
    for key, belief in state.hypotheses.items():
        ev = by_key.get(key)
        likelihood = L_NONE if ev is None else (L_MATCH if ev["matched"] else L_MISMATCH)
        weighted[key] = belief.confidence * likelihood
    other = state.other * L_NONE
    total = sum(weighted.values()) + other
    for key, belief in state.hypotheses.items():
        before = belief.confidence
        belief.confidence = weighted[key] / total if total else before
        ev = by_key.get(key)
        if ev is not None:
            if ev["matched"]:
                belief.support += 1
                if discriminating:
                    belief.discriminating_support += 1
            else:
                belief.contradictions += 1
        belief.history.append(
            {
                "experiment": experiment_key,
                "before": round(before, 4),
                "after": round(belief.confidence, 4),
                "matched": None if ev is None else ev["matched"],
                "reason": None if ev is None else ev["reason"],
            }
        )
        belief.status = classify(belief)
    state.other = other / total if total else state.other
    return state


def classify(belief: HypothesisBelief) -> str:
    if belief.contradictions and belief.confidence < REFUTE_THRESHOLD:
        return "refuted"
    if belief.confidence >= CONFIRM_THRESHOLD and belief.discriminating_support and not belief.contradictions:
        return "confirmed"
    if belief.support and not belief.contradictions:
        return "supported"
    if belief.contradictions:
        return "weakened"
    return "open"
