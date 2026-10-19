"""Orchestrator behaviour with the mock provider and a scripted (non-Docker) sandbox."""

import pytest

from agents.orchestrator import Orchestrator
from core.database import session_scope
from core.models import Event, Experiment, Hypothesis, Investigation, ModelCall, Patch, Repository
from services.repo_analysis import profile_repository
from services.settings_service import RuntimeConfigUpdate, reset_runtime_config, update_runtime_config
from tests.fakes import TARGET, FakeSandbox


@pytest.fixture
def investigation(demo_copy):
    def make(mode="forge", target=TARGET):
        with session_scope() as db:
            repo = Repository(
                name="demo-copy",
                source_type="local",
                source=str(demo_copy),
                snapshot_path=str(demo_copy),
                profile=profile_repository(demo_copy),
            )
            db.add(repo)
            db.flush()
            inv = Investigation(
                repository_id=repo.id, title="t", target_test=target, mode=mode, usage={}, budget={}
            )
            db.add(inv)
            db.flush()
            return inv.id

    return make


@pytest.fixture(autouse=True)
def _reset_settings():
    yield
    with session_scope() as db:
        reset_runtime_config(db)


def load(inv_id):
    with session_scope() as db:
        inv = db.get(Investigation, inv_id)
        return {
            "inv": inv,
            "hyps": {h.key: h for h in db.query(Hypothesis).filter_by(investigation_id=inv_id)},
            "exps": db.query(Experiment)
            .filter_by(investigation_id=inv_id)
            .order_by(Experiment.created_at)
            .all(),
            "patches": db.query(Patch).filter_by(investigation_id=inv_id).order_by(Patch.created_at).all(),
            "events": [e.type for e in db.query(Event).filter_by(investigation_id=inv_id).order_by(Event.id)],
            "calls": db.query(ModelCall).filter_by(investigation_id=inv_id).all(),
        }


def test_forge_flow_confirms_hypothesis_and_verifies_patch(investigation):
    inv_id = investigation()
    sandbox = FakeSandbox()
    Orchestrator(inv_id, sandbox=sandbox).run()
    state = load(inv_id)
    inv = state["inv"]
    assert inv.status == "completed" and inv.verdict == "verified_fix", inv.error
    assert inv.simulated and inv.provider == "mock"
    assert state["hyps"]["H1"].status == "confirmed"
    assert {state["hyps"]["H2"].status, state["hyps"]["H3"].status} == {"refuted"}
    assert [e.key for e in state["exps"]] == ["E0", "E1", "E2", "E3"]
    assert state["exps"][0].kind == "reproduction" and state["exps"][0].outcome == "fail"
    assert state["exps"][1].outcome == "fail" and state["exps"][2].outcome == "pass"
    assert state["patches"][0].status == "verified"
    assert state["patches"][0].verification["fixed"] == [TARGET]
    assert "-  return allowed.length === 0 || allowed.includes(to);" in state["patches"][0].diff
    assert all(c.simulated for c in state["calls"])
    assert inv.usage["experiments"] == 3
    assert "belief_update" in state["events"] and state["events"][-1] == "completed"
    # experiments ran on copies that contained the experiment file, never on the snapshot itself
    exp_calls = [c for c in sandbox.calls if any("forge-experiments" in t for t in c.targets)]
    assert exp_calls and all("workspaces" in str(c.workspace) for c in exp_calls)


def test_verifier_rejects_patch_that_causes_regression(investigation):
    inv_id = investigation()
    Orchestrator(inv_id, sandbox=FakeSandbox(break_regression=True)).run()
    state = load(inv_id)
    assert state["inv"].verdict == "no_verified_fix"
    first = state["patches"][0]
    assert first.status == "rejected"
    assert first.verification["regressions"] == [
        "payment capture > records separate charges for separate capture calls"
    ]
    assert state["patches"][-1].status == "empty"  # mock has no further scripted attempt and invents nothing


def test_baseline_mode_skips_experiments(investigation):
    inv_id = investigation(mode="baseline")
    Orchestrator(inv_id, sandbox=FakeSandbox()).run()
    state = load(inv_id)
    assert state["inv"].verdict == "verified_fix"
    assert state["inv"].summary["claimed_fixed"] is True
    assert not state["hyps"]
    assert [e.key for e in state["exps"]] == ["E0"]


def test_model_call_budget_terminates_investigation(investigation):
    with session_scope() as db:
        update_runtime_config(db, RuntimeConfigUpdate(max_model_calls=2))
    inv_id = investigation()
    Orchestrator(inv_id, sandbox=FakeSandbox()).run()
    state = load(inv_id)
    assert state["inv"].verdict == "inconclusive"
    assert "budget" in (state["inv"].error or "")
    assert "budget_exhausted" in state["events"]
    assert not state["patches"]


def test_experiment_budget_is_respected(investigation):
    with session_scope() as db:
        update_runtime_config(db, RuntimeConfigUpdate(max_experiments=1))
    inv_id = investigation()
    Orchestrator(inv_id, sandbox=FakeSandbox()).run()
    state = load(inv_id)
    assert [e.key for e in state["exps"]] == ["E0", "E1"]


def test_unavailable_sandbox_fails_cleanly(investigation):
    inv_id = investigation()
    Orchestrator(inv_id, sandbox=FakeSandbox(available=False)).run()
    inv = load(inv_id)["inv"]
    assert inv.status == "failed"
    assert "Sandbox" in inv.error


def test_unknown_target_reports_no_failure(investigation):
    inv_id = investigation(target="a test that does not exist")
    Orchestrator(inv_id, sandbox=FakeSandbox()).run()
    inv = load(inv_id)["inv"]
    assert inv.verdict == "no_failure_observed"
