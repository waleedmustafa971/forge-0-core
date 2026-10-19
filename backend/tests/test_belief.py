import pytest

from agents.belief import apply_evidence, evaluate, initial_state, is_discriminating


def test_initial_state_reserves_unexplained_mass():
    state = initial_state({"H1": 0.5, "H2": 0.5})
    assert state.other == pytest.approx(0.1)
    assert sum(h.confidence for h in state.hypotheses.values()) + state.other == pytest.approx(1.0)


def test_matching_prediction_increases_and_contradiction_refutes():
    state = initial_state({"H1": 0.5, "H2": 0.4})
    preds = [{"hypothesis": "H1", "outcome": "fail"}, {"hypothesis": "H2", "outcome": "pass"}]
    evals = evaluate(preds, "fail", "")
    apply_evidence(state, "E1", evals, is_discriminating(preds))
    apply_evidence(state, "E2", evals, True)
    h1, h2 = state.hypotheses["H1"], state.hypotheses["H2"]
    assert h1.confidence > 0.75 and h1.status == "confirmed"
    assert h2.confidence < 0.1 and h2.status == "refuted"
    assert sum(h.confidence for h in state.hypotheses.values()) + state.other == pytest.approx(1.0)
    assert state.decisive
    assert [s["experiment"] for s in h1.history] == ["E1", "E2"]


def test_output_contains_is_part_of_prediction():
    preds = [{"hypothesis": "H1", "outcome": "fail", "output_contains": "key changed"}]
    assert evaluate(preds, "fail", "AssertionError: key changed between attempts")[0]["matched"]
    assert not evaluate(preds, "fail", "AssertionError: something else")[0]["matched"]


def test_non_discriminating_experiment_cannot_confirm():
    state = initial_state({"H1": 0.9, "H2": 0.1})
    preds = [{"hypothesis": "H1", "outcome": "fail"}, {"hypothesis": "H2", "outcome": "fail"}]
    assert not is_discriminating(preds)
    for key in ("E1", "E2", "E3"):
        apply_evidence(state, key, evaluate(preds, "fail", ""), False)
    assert state.hypotheses["H1"].status == "supported"
    assert not state.decisive


def test_refuting_everything_moves_mass_to_unexplained():
    state = initial_state({"H1": 0.5, "H2": 0.5})
    preds = [{"hypothesis": "H1", "outcome": "pass"}, {"hypothesis": "H2", "outcome": "pass"}]
    apply_evidence(state, "E1", evaluate(preds, "fail", ""), False)
    apply_evidence(state, "E2", evaluate(preds, "fail", ""), False)
    assert state.other > 0.5
    assert all(h.status in ("refuted", "weakened") for h in state.hypotheses.values())
