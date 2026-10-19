"""Agent C — Experiment Designer.

Asks the model for discriminating experiments, then validates each one against the
sandbox contract before anything is executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.base import InvestigationContext
from agents.belief import is_discriminating
from agents.prompts import experiments_prompt
from core.schemas import ExperimentDraft, ExperimentPlan, InvestigationReport
from sandbox.runners import RunnerValidationError, get_runner, validate_pattern
from services.workspace import EditError, is_test_path, safe_relative


@dataclass
class ValidatedExperiment:
    draft: ExperimentDraft
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


class ExperimentDesigner:
    name = "experiment_designer"

    def __init__(self, ctx: InvestigationContext) -> None:
        self.ctx = ctx

    def run(
        self,
        report: InvestigationReport,
        hypotheses: list[dict[str, Any]],
        history: list[dict[str, Any]],
        round_index: int,
    ) -> tuple[ExperimentPlan, list[ValidatedExperiment]]:
        ctx = self.ctx
        ctx.set_phase(f"designing experiments (round {round_index + 1})", self.name)
        remaining = ctx.budget.experiments_remaining()
        system, user = experiments_prompt(report, hypotheses, history, remaining, round_index)
        plan = ctx.call_model(
            agent=self.name,
            task="experiments",
            system=system,
            user=user,
            context={
                "target_test": report.target_failure.test_name if report.target_failure else None,
                "round": round_index,
                "hypotheses": [h["key"] for h in hypotheses],
            },
            schema=ExperimentPlan,
        )
        known = {h["key"] for h in hypotheses if h.get("status") != "refuted"} | {
            h["key"] for h in hypotheses
        }
        validated = [self.validate(d, known, report) for d in plan.experiments[: max(remaining, 0)]]
        if len(plan.experiments) > remaining:
            ctx.emit(
                self.name,
                "warning",
                f"Plan proposed {len(plan.experiments)} experiments; experiment budget allows {remaining}",
            )
        return plan, validated

    def validate(
        self, draft: ExperimentDraft, known: set[str], report: InvestigationReport
    ) -> ValidatedExperiment:
        v = ValidatedExperiment(draft)
        runner_name = report.runtime.runner
        if runner_name is None:
            v.errors.append("Repository has no supported runner")
            return v
        runner = get_runner(runner_name)
        try:
            runner.argv(draft.run, draft.test_name_pattern)
            validate_pattern(draft.test_name_pattern)
        except RunnerValidationError as exc:
            v.errors.append(str(exc))
        new_paths = {f.path.strip().replace("\\", "/").removeprefix("./") for f in draft.files}
        for item in draft.files:
            try:
                target = safe_relative(self.ctx.snapshot, item.path)
                if target.exists():
                    v.errors.append(f"Experiment file {item.path} would overwrite an existing file")
            except EditError as exc:
                v.errors.append(str(exc))
        for edit in draft.source_edits:
            if is_test_path(edit.file):
                v.errors.append(f"Interventions may not edit test files ({edit.file})")
        for target in draft.run:
            clean = target.replace("\\", "/").removeprefix("./")
            if "*" not in clean and clean not in new_paths and not (self.ctx.snapshot / clean).exists():
                v.errors.append(f"Run target {target} does not exist and is not created by the experiment")
        predicted = {p.hypothesis for p in draft.predictions}
        unknown = predicted - known
        if unknown:
            v.errors.append(f"Predictions reference unknown hypotheses: {sorted(unknown)}")
        if not draft.predictions:
            v.errors.append("Experiment makes no predictions")
        elif not is_discriminating([p.model_dump() for p in draft.predictions]):
            v.warnings.append("All hypotheses predict the same result; the experiment cannot discriminate")
        return v
