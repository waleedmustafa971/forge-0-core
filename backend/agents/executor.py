"""Agent D — Experiment Executor.

Materialises an experiment in a disposable copy (new test files + counterfactual source
edits) and runs it in the Docker sandbox. Infrastructure failures are retried once.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.base import InvestigationContext
from core.schemas import ExecutionResult, ExperimentDraft
from services.workspace import EditError, add_files, apply_edits

LOAD_ERROR_NAMES = {"SyntaxError"}
LOAD_ERROR_CODES = {
    "ERR_MODULE_NOT_FOUND",
    "ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX",
    "ERR_INVALID_TYPESCRIPT_SYNTAX",
}


@dataclass
class ExperimentRun:
    outcome: str  # pass | fail | error | timeout
    detail: str
    result: ExecutionResult | None
    intervention_diff: str = ""
    attempts: int = 1


def classify(result: ExecutionResult, targets: list[str]) -> tuple[str, str]:
    if result.infra_error:
        return "error", f"Sandbox error: {result.infra_error[:200]}"
    if result.timed_out:
        return "timeout", "Experiment exceeded its time limit"
    run = result.test_run
    if run is None or not run.parse_ok or run.total == 0:
        tail = (result.stderr or result.stdout)[-300:]
        return "error", f"No tests were executed (exit {result.exit_code}). {tail}"
    normalized_targets = {t.replace("\\", "/") for t in targets}
    for test in run.failing():
        if test.error_name in LOAD_ERROR_NAMES or test.error_code in LOAD_ERROR_CODES:
            return "error", f"Experiment could not load: {test.error_name}: {(test.error or '')[:200]}"
        if test.name in normalized_targets or test.name.endswith((".ts", ".js", ".mjs", ".py")):
            return "error", f"Test file failed to load: {(test.error or '')[:200]}"
    if run.failed:
        return "fail", f"{run.failed} of {run.total} executed tests failed"
    if run.passed:
        return "pass", f"All {run.passed} executed tests passed"
    return "error", "Every executed test was skipped"


def observation_text(result: ExecutionResult | None) -> str:
    if result is None:
        return ""
    parts = []
    if result.test_run:
        for test in result.test_run.failing():
            parts.append(f"{test.name}: {test.error_name}: {test.error}")
    parts += [result.stdout[-20000:], result.stderr[-5000:]]
    return "\n".join(p for p in parts if p)


class ExperimentExecutor:
    name = "experiment_executor"

    def __init__(self, ctx: InvestigationContext) -> None:
        self.ctx = ctx

    def run(self, key: str, draft: ExperimentDraft) -> ExperimentRun:
        ctx = self.ctx
        assert ctx.report is not None and ctx.report.runtime.runner is not None
        ws = ctx.workspaces.create(ctx.snapshot, ctx.investigation_id, f"exp-{key}")
        try:
            try:
                add_files(ws, draft.files)
                diff = ""
                if draft.source_edits:
                    diff = apply_edits(
                        ws, draft.source_edits, allow_test_files=False, allow_create=False
                    ).diff
            except EditError as exc:
                return ExperimentRun("error", f"Experiment could not be materialised: {exc}", None)
            attempts = 0
            result: ExecutionResult | None = None
            for attempt in range(2):
                attempts = attempt + 1
                ctx.checkpoint()
                result = ctx.sandbox.run_tests(
                    ws, ctx.report.runtime.runner, draft.run, draft.test_name_pattern
                )
                ctx.budget.sandbox_runs += 1
                if not result.infra_error:
                    break
                ctx.emit(
                    self.name,
                    "retry",
                    f"{key}: sandbox infrastructure error, retrying once ({result.infra_error[:120]})",
                )
            assert result is not None
            outcome, detail = classify(result, draft.run)
            return ExperimentRun(outcome, detail, result, diff, attempts)
        finally:
            if not ctx.workspaces_keep:
                ctx.workspaces.discard(ws)
