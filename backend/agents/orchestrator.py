"""Agent G — Orchestrator.

Runs one investigation end to end and records every hypothesis, experiment, result and
decision. Two modes:

* ``forge``    — System B: hypothesis-driven, counterfactual debugging.
* ``baseline`` — Baseline A: direct one-shot repair from the failure context. The
  verifier still runs afterwards, purely to *measure* the baseline; its verdict does
  not feed back into the repair.
"""

from __future__ import annotations

import logging
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.base import (
    AgentError,
    BudgetExceededError,
    InvestigationCancelledError,
    InvestigationContext,
    build_budget,
    dump,
)
from agents.belief import BeliefState, apply_evidence, evaluate, initial_state, is_discriminating
from agents.executor import ExperimentExecutor, observation_text
from agents.experiment_designer import ExperimentDesigner
from agents.hypothesis import HypothesisGenerator
from agents.investigator import RepositoryInvestigator, isolation_pattern
from agents.repair import RepairEngineer
from agents.verifier import IndependentVerifier
from core.config import get_settings
from core.database import session_scope
from core.models import Experiment, Hypothesis, Investigation, Patch, Repository
from core.schemas import ExecutionResult, ExperimentDraft, InvestigationReport, PatchDraft, VerificationReport
from providers.base import AIProvider
from providers.registry import build_provider
from sandbox.docker import DockerSandbox, get_sandbox
from services.settings_service import get_runtime_config
from services.workspace import EditError, WorkspaceManager

log = logging.getLogger(__name__)
NAME = "orchestrator"
MIN_REPAIR_CONFIDENCE = 0.5


def _now() -> datetime:
    return datetime.now(UTC)


def _result_payload(result: ExecutionResult | None) -> dict[str, Any] | None:
    return dump(result) if result is not None else None


class Orchestrator:
    def __init__(
        self,
        investigation_id: str,
        *,
        sandbox: DockerSandbox | None = None,
        provider: AIProvider | None = None,
    ) -> None:
        self.investigation_id = investigation_id
        self._sandbox = sandbox
        self._provider = provider
        self.ctx: InvestigationContext | None = None
        self.beliefs: BeliefState | None = None
        self.hypothesis_ids: dict[str, str] = {}
        self.experiment_counter = 0
        self.evidence: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ setup
    def _build_context(self) -> InvestigationContext:
        settings = get_settings()
        with session_scope() as db:
            inv = db.get(Investigation, self.investigation_id)
            if inv is None:
                raise AgentError("Investigation not found")
            repo = db.get(Repository, inv.repository_id)
            assert repo is not None
            config = get_runtime_config(db)
            if self._provider is not None:
                provider, note = self._provider, None
            else:
                selection = build_provider(config)
                provider, note = selection.provider, selection.fallback_reason
            budget = build_budget(config)
            inv.status = "running"
            inv.phase = "starting"
            inv.started_at = _now()
            inv.provider = provider.name
            inv.model = provider.model
            inv.simulated = provider.simulated
            inv.provider_note = note
            inv.budget = budget.limits()
            ctx = InvestigationContext(
                investigation_id=inv.id,
                repository_name=repo.name,
                snapshot=Path(repo.snapshot_path),
                mode=inv.mode,
                symptom=inv.symptom,
                target_test=inv.target_test,
                provider=provider,
                sandbox=self._sandbox or get_sandbox(),
                workspaces=WorkspaceManager(),
                budget=budget,
                workspaces_keep=settings.keep_workspaces,
            )
        mode_label = (
            "System B (hypothesis-driven)" if ctx.mode == "forge" else "Baseline A (direct one-shot repair)"
        )
        ctx.emit(
            NAME,
            "started",
            f"Investigation started — {mode_label}; provider {provider.name}/{provider.model}"
            + (" [SIMULATED: scripted mock responses]" if provider.simulated else ""),
            {
                "mode": ctx.mode,
                "provider": provider.describe(),
                "budget": budget.limits(),
                "provider_note": note,
            },
        )
        if note:
            ctx.emit(NAME, "warning", note)
        return ctx

    # -------------------------------------------------------------- persistence
    def _update(self, **fields: Any) -> None:
        with session_scope() as db:
            inv = db.get(Investigation, self.investigation_id)
            if inv is None:
                return
            for key, value in fields.items():
                setattr(inv, key, value)
            if self.ctx:
                inv.usage = self.ctx.budget.usage()

    def _next_key(self) -> str:
        self.experiment_counter += 1
        return f"E{self.experiment_counter}"

    def _record_reproduction(self, report: InvestigationReport, run: ExecutionResult | None) -> None:
        if run is None or report.target_failure is None:
            return
        outcome = "fail" if report.reproduction_confirmed else ("error" if run.infra_error else "pass")
        with session_scope() as db:
            db.add(
                Experiment(
                    investigation_id=self.investigation_id,
                    key="E0",
                    round=0,
                    designed_by="investigator",
                    kind="reproduction",
                    objective="Control: re-run the target test in isolation to confirm it reproduces",
                    hypothesis_keys=[],
                    predictions=[],
                    spec={
                        "run": [report.target_failure.file],
                        "test_name_pattern": isolation_pattern(report.target_failure.test_name),
                        "files": [],
                        "source_edits": [],
                    },
                    status="completed",
                    outcome=outcome,
                    result=_result_payload(run),
                    evaluation={
                        "detail": "reproduced" if report.reproduction_confirmed else "did not reproduce"
                    },
                    attempts=1,
                    started_at=_now(),
                    finished_at=_now(),
                )
            )

    def _persist_hypotheses(self, drafts: list[Any]) -> None:
        assert self.beliefs is not None
        with session_scope() as db:
            for rank, draft in enumerate(drafts):
                row = Hypothesis(
                    investigation_id=self.investigation_id,
                    key=draft.key,
                    title=draft.title,
                    explanation=draft.explanation,
                    suspected_locations=draft.suspected_locations,
                    supporting_evidence=draft.supporting_evidence,
                    contradicting_evidence=draft.contradicting_evidence,
                    prior=draft.prior,
                    confidence=self.beliefs.hypotheses[draft.key].confidence,
                    status="open",
                    rank=rank + 1,
                    history=[],
                )
                db.add(row)
                db.flush()
                self.hypothesis_ids[draft.key] = row.id

    def _sync_beliefs(self) -> None:
        assert self.beliefs is not None
        ranked = self.beliefs.ranked()
        with session_scope() as db:
            for rank, belief in enumerate(ranked, start=1):
                row = db.get(Hypothesis, self.hypothesis_ids[belief.key])
                if row is None:
                    continue
                row.confidence = belief.confidence
                row.status = belief.status
                row.rank = rank
                row.history = list(belief.history)
            inv = db.get(Investigation, self.investigation_id)
            if inv is not None:
                summary = dict(inv.summary or {})
                summary["belief"] = self.beliefs.snapshot()
                inv.summary = summary

    def _hypotheses_view(self) -> list[dict[str, Any]]:
        with session_scope() as db:
            rows = (
                db.query(Hypothesis)
                .filter_by(investigation_id=self.investigation_id)
                .order_by(Hypothesis.rank)
            )
            return [
                {
                    "key": h.key,
                    "title": h.title,
                    "explanation": h.explanation,
                    "suspected_locations": h.suspected_locations,
                    "confidence": round(h.confidence, 3),
                    "status": h.status,
                }
                for h in rows
            ]

    # ---------------------------------------------------------------- forge flow
    def _run_experiment(
        self, draft: ExperimentDraft, round_index: int, errors: list[str], warnings: list[str]
    ) -> None:
        ctx = self.ctx
        assert ctx is not None and self.beliefs is not None
        key = self._next_key()
        predictions = [p.model_dump() for p in draft.predictions]
        spec = {
            "proposed_key": draft.key,
            "files": [f.model_dump() for f in draft.files],
            "source_edits": [e.model_dump() for e in draft.source_edits],
            "run": draft.run,
            "test_name_pattern": draft.test_name_pattern,
            "success_condition": draft.success_condition,
            "failure_condition": draft.failure_condition,
            "discriminating": is_discriminating(predictions),
            "warnings": warnings,
        }
        with session_scope() as db:
            row = Experiment(
                investigation_id=self.investigation_id,
                key=key,
                round=round_index + 1,
                kind=draft.kind,
                objective=draft.objective,
                hypothesis_keys=draft.hypotheses,
                predictions=predictions,
                spec=spec,
                status="invalid" if errors else "running",
                outcome="error" if errors else None,
                evaluation={"errors": errors} if errors else None,
                started_at=_now(),
                finished_at=_now() if errors else None,
            )
            db.add(row)
            db.flush()
            row_id = row.id
        if errors:
            ctx.emit(
                "experiment_designer",
                "experiment_rejected",
                f"{key} rejected before execution: {'; '.join(errors)[:300]}",
                {"key": key, "errors": errors},
            )
            return
        ctx.emit(
            "experiment_designer",
            "experiment_planned",
            f"{key} [{draft.kind}] {draft.objective}",
            {
                "key": key,
                "kind": draft.kind,
                "predictions": predictions,
                "discriminating": spec["discriminating"],
            },
        )
        ctx.set_phase(f"executing {key}", "experiment_executor")
        ctx.budget.experiments += 1
        run = ExperimentExecutor(ctx).run(key, draft)
        output = observation_text(run.result)
        evaluations: list[dict[str, Any]] = []
        snapshot_before = self.beliefs.snapshot()
        if run.outcome in ("pass", "fail"):
            evaluations = evaluate(predictions, run.outcome, output)
            apply_evidence(self.beliefs, key, evaluations, bool(spec["discriminating"]))
            self._sync_beliefs()
        evaluation = {
            "detail": run.detail,
            "predictions": evaluations,
            "belief_before": snapshot_before,
            "belief_after": self.beliefs.snapshot(),
            "intervention_diff": run.intervention_diff,
            "informative": bool(evaluations),
        }
        with session_scope() as db:
            row = db.get(Experiment, row_id)
            assert row is not None
            row.status = "completed" if run.result is not None else "invalid"
            row.outcome = run.outcome
            row.result = _result_payload(run.result)
            row.evaluation = evaluation
            row.attempts = run.attempts
            row.finished_at = _now()
        self.evidence.append(
            {
                "experiment": key,
                "objective": draft.objective,
                "kind": draft.kind,
                "outcome": run.outcome,
                "detail": run.detail,
                "predictions": evaluations,
                "failure_messages": [
                    f"{t.name}: {t.error}"
                    for t in (run.result.test_run.failing() if run.result and run.result.test_run else [])
                ][:5],
            }
        )
        matched = [e["hypothesis"] for e in evaluations if e["matched"]]
        contradicted = [e["hypothesis"] for e in evaluations if not e["matched"]]
        ctx.emit(
            "experiment_executor",
            "experiment_result",
            f"{key}: {run.outcome.upper()} — {run.detail}"
            + (f"; consistent with {', '.join(matched)}" if matched else "")
            + (f"; contradicts {', '.join(contradicted)}" if contradicted else ""),
            {
                "key": key,
                "outcome": run.outcome,
                "duration_ms": run.result.duration_ms if run.result else None,
                "matched": matched,
                "contradicted": contradicted,
            },
        )
        if evaluations:
            ranked = ", ".join(f"{h.key} {h.confidence:.2f} ({h.status})" for h in self.beliefs.ranked())
            ctx.emit(
                NAME,
                "belief_update",
                f"Ranking after {key}: {ranked}; unexplained {self.beliefs.other:.2f}",
                {"after": self.beliefs.snapshot(), "before": snapshot_before},
            )

    def _forge(self, report: InvestigationReport) -> None:
        ctx = self.ctx
        assert ctx is not None
        hypothesis_set = HypothesisGenerator(ctx).run(report)
        drafts = hypothesis_set.hypotheses
        self.beliefs = initial_state({d.key: d.prior for d in drafts})
        self._persist_hypotheses(drafts)
        self._sync_beliefs()
        ctx.emit(
            "hypothesis_generator",
            "hypotheses",
            f"{len(drafts)} competing hypotheses: " + "; ".join(f"{d.key} {d.title}" for d in drafts),
            {"reasoning_summary": hypothesis_set.reasoning_summary, "keys": [d.key for d in drafts]},
        )

        designer = ExperimentDesigner(ctx)
        stop_reason = "experiment rounds exhausted"
        for round_index in range(ctx.budget.max_experiment_rounds):
            if ctx.budget.experiments_remaining() == 0:
                stop_reason = "experiment budget exhausted"
                break
            plan, validated = designer.run(report, self._hypotheses_view(), self.evidence, round_index)
            ctx.emit(
                "experiment_designer",
                "plan",
                f"Round {round_index + 1}: {len(validated)} experiment(s) proposed — {plan.rationale[:240]}",
                {"rationale": plan.rationale, "count": len(validated), "conclude": plan.conclude},
            )
            for v in validated:
                if ctx.budget.experiments_remaining() == 0:
                    break
                self._run_experiment(v.draft, round_index, v.errors, v.warnings)
            if self.beliefs.decisive:
                leader = self.beliefs.leader()
                assert leader is not None
                stop_reason = f"{leader.key} confirmed by discriminating evidence"
                break
            if plan.conclude or not validated:
                stop_reason = "designer reported no further informative experiments"
                break
        leader = self.beliefs.leader()
        assert leader is not None
        ctx.emit(
            NAME,
            "decision",
            f"Experimentation stopped: {stop_reason}. Leading hypothesis {leader.key} "
            f"(confidence {leader.confidence:.2f}, {leader.status}).",
            {"stop_reason": stop_reason, "leader": leader.key, "confidence": leader.confidence},
        )
        if leader.confidence < MIN_REPAIR_CONFIDENCE and leader.status != "confirmed":
            self._finish(
                "inconclusive",
                f"Evidence is insufficient to act on: leading hypothesis {leader.key} has confidence "
                f"{leader.confidence:.2f}. No patch was attempted.",
                report,
            )
            return
        leader_view = next(h for h in self._hypotheses_view() if h["key"] == leader.key)
        self._repair_loop(report, leader_view)

    def _repair_loop(self, report: InvestigationReport, leader: dict[str, Any]) -> None:
        ctx = self.ctx
        assert ctx is not None and report.target_failure is not None
        engineer = RepairEngineer(ctx)
        verifier = IndependentVerifier(ctx)
        previous: list[dict[str, Any]] = []
        for attempt in range(ctx.budget.max_repair_attempts):
            draft = engineer.propose(report, leader, self.evidence, previous, attempt)
            verification = self._evaluate_patch(
                draft, attempt, report.target_failure.test_name, engineer, verifier
            )
            if verification is None:
                previous.append(
                    {"attempt": attempt + 1, "summary": draft.summary, "rejected_because": "no edits"}
                )
                if not draft.edits:
                    break
                continue
            if verification.verdict == "verified":
                self._finish(
                    "verified_fix", f"Patch P{attempt + 1} verified: {verification.reasons[0]}", report
                )
                return
            previous.append(
                {
                    "attempt": attempt + 1,
                    "summary": draft.summary,
                    "edits": [e.model_dump() for e in draft.edits],
                    "verifier_reasons": verification.reasons,
                    "regressions": verification.regressions,
                    "target_after_patch": verification.target_patched,
                }
            )
            ctx.emit(
                NAME,
                "decision",
                f"P{attempt + 1} rejected by the verifier; "
                + (
                    "requesting a revised repair"
                    if attempt + 1 < ctx.budget.max_repair_attempts
                    else "repair budget exhausted"
                ),
            )
        self._finish("no_verified_fix", "No candidate patch passed independent verification.", report)

    def _evaluate_patch(
        self,
        draft: PatchDraft,
        attempt: int,
        target: str,
        engineer: RepairEngineer,
        verifier: IndependentVerifier,
    ) -> VerificationReport | None:
        ctx = self.ctx
        assert ctx is not None
        key = f"P{attempt + 1}"
        with session_scope() as db:
            row = Patch(
                investigation_id=self.investigation_id,
                key=key,
                attempt=attempt + 1,
                hypothesis_key=draft.hypothesis,
                summary=draft.summary,
                rationale=draft.rationale,
                edits=[e.model_dump() for e in draft.edits],
                status="proposed",
                verification=None,
            )
            db.add(row)
            db.flush()
            patch_id = row.id
        if not draft.edits:
            self._set_patch(patch_id, status="empty")
            ctx.emit("repair_engineer", "patch_empty", f"{key}: no patch proposed — {draft.summary}")
            return None
        try:
            applied = engineer.materialize(draft, key)
        except EditError as exc:
            self._set_patch(
                patch_id, status="apply_failed", verification={"verdict": "rejected", "reasons": [str(exc)]}
            )
            ctx.emit("repair_engineer", "patch_apply_failed", f"{key} could not be applied: {exc}")
            return VerificationReport(
                verdict="rejected",
                reasons=[f"Patch could not be applied: {exc}"],
                target_test=target,
                target_baseline="failed",
                target_patched=None,
            )
        self._set_patch(patch_id, diff=applied.diff, files_changed=applied.files_changed(), status="applied")
        ctx.emit(
            "repair_engineer",
            "patch_proposed",
            f"{key}: {draft.summary} ({len(applied.changes)} file(s) changed)",
            {"key": key, "files": applied.files_changed(), "risk_notes": draft.risk_notes},
        )
        verification = verifier.verify(draft.edits, target, key)
        self._set_patch(
            patch_id,
            status="verified" if verification.verdict == "verified" else "rejected",
            verification=dump(verification),
        )
        return verification

    def _set_patch(self, patch_id: str, **fields: Any) -> None:
        with session_scope() as db:
            row = db.get(Patch, patch_id)
            if row is not None:
                for key, value in fields.items():
                    setattr(row, key, value)

    # ------------------------------------------------------------- baseline flow
    def _baseline(self, report: InvestigationReport) -> None:
        ctx = self.ctx
        assert ctx is not None and report.target_failure is not None
        engineer = RepairEngineer(ctx)
        verifier = IndependentVerifier(ctx)
        draft = engineer.propose_one_shot(report)
        verification = self._evaluate_patch(draft, 0, report.target_failure.test_name, engineer, verifier)
        verified = verification is not None and verification.verdict == "verified"
        self._finish(
            "verified_fix" if verified else "no_verified_fix",
            "Baseline A applied its one-shot patch without experiments; the verifier was run afterwards "
            "only to measure it: "
            + (verification.reasons[0] if verification and verification.reasons else "no patch"),
            report,
            claimed_fixed=bool(draft.edits),
        )

    # -------------------------------------------------------------------- finish
    def _finish(
        self, verdict: str, message: str, report: InvestigationReport, claimed_fixed: bool | None = None
    ) -> None:
        ctx = self.ctx
        assert ctx is not None
        root_cause = None
        with session_scope() as db:
            inv = db.get(Investigation, self.investigation_id)
            assert inv is not None
            hyps = sorted(inv.hypotheses, key=lambda h: h.rank)
            if hyps and verdict in ("verified_fix", "no_verified_fix", "inconclusive"):
                top = hyps[0]
                root_cause = f"{top.key}: {top.title} — {top.explanation}"
            summary = dict(inv.summary or {})
            summary.update(
                {
                    "verdict": verdict,
                    "message": message,
                    "claimed_fixed": claimed_fixed
                    if claimed_fixed is not None
                    else verdict == "verified_fix",
                    "reproduced": report.reproduction_confirmed,
                    "experiments_run": ctx.budget.experiments,
                    "patch_attempts": len(inv.patches),
                }
            )
            inv.summary = summary
            inv.verdict = verdict
            inv.root_cause = root_cause
            inv.status = "completed"
            inv.phase = "completed"
            inv.active_agent = None
            inv.finished_at = _now()
            inv.usage = ctx.budget.usage()
        ctx.emit(NAME, "completed", f"Investigation completed: {verdict} — {message}", {"verdict": verdict})

    # ---------------------------------------------------------------------- run
    def run(self) -> None:
        try:
            self.ctx = self._build_context()
        except Exception as exc:
            log.exception("failed to start investigation")
            self._update(status="failed", phase="failed", error=str(exc), finished_at=_now())
            return
        ctx = self.ctx
        try:
            report, reproduction = RepositoryInvestigator(ctx).run()
            ctx.report = report
            self._update(investigation_report=dump(report))
            self._record_reproduction(report, reproduction)
            if report.target_failure is None:
                self._finish(
                    "no_failure_observed",
                    "No failing test was observed; nothing to investigate. " + " ".join(report.notes),
                    report,
                )
                return
            if ctx.mode == "baseline":
                self._baseline(report)
            else:
                self._forge(report)
        except InvestigationCancelledError as exc:
            ctx.emit(NAME, "cancelled", f"Investigation cancelled: {exc}")
            self._update(status="cancelled", phase="cancelled", active_agent=None, finished_at=_now())
        except BudgetExceededError as exc:
            ctx.emit(NAME, "budget_exhausted", f"Terminating: {exc}")
            self._update(
                status="completed",
                phase="completed",
                verdict="inconclusive",
                active_agent=None,
                error=str(exc),
                finished_at=_now(),
            )
        except Exception as exc:
            log.exception("investigation failed", extra={"investigation": self.investigation_id})
            ctx.emit(
                NAME, "error", f"Investigation failed: {exc}", {"traceback": traceback.format_exc()[-4000:]}
            )
            self._update(
                status="failed", phase="failed", active_agent=None, error=str(exc), finished_at=_now()
            )
        finally:
            if not ctx.workspaces_keep:
                ctx.workspaces.cleanup(self.investigation_id)
