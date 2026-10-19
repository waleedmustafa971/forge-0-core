"""Agent F — Independent Verifier.

Re-applies the stored edits to a fresh copy (it does not trust the Repair Engineer's
working copy), runs the full suite on both the original and the patched code, re-runs the
target test in isolation, and compares behaviour test by test. A patch is accepted only
if the target test now passes every time and no previously passing test regresses.
"""

from __future__ import annotations

from agents.base import InvestigationContext
from agents.investigator import isolation_pattern
from core.schemas import ExecutionResult, SourceEdit, TestDelta, VerificationReport
from sandbox.tap import find_test
from services.workspace import EditError, apply_edits

TARGET_REPEATS = 2


def _status_map(result: ExecutionResult) -> dict[str, str]:
    if not result.test_run:
        return {}
    return {t.name: t.status for t in result.test_run.tests}


def compare(
    baseline: ExecutionResult,
    patched: ExecutionResult,
    target: str | None,
    repeats: list[str],
) -> VerificationReport:
    reasons: list[str] = []
    if patched.infra_error or baseline.infra_error:
        return VerificationReport(
            verdict="error",
            reasons=[f"Sandbox error: {patched.infra_error or baseline.infra_error}"],
            target_test=target,
            target_baseline=None,
            target_patched=None,
            baseline_run=baseline,
            patched_run=patched,
        )
    before, after = _status_map(baseline), _status_map(patched)
    names = sorted(set(before) | set(after))
    deltas = [TestDelta(name=n, baseline=before.get(n), patched=after.get(n)) for n in names]
    fixed = [d.name for d in deltas if d.baseline == "failed" and d.patched == "passed"]
    regressions = [d.name for d in deltas if d.baseline == "passed" and d.patched != "passed"]
    still_failing = [d.name for d in deltas if d.baseline == "failed" and d.patched == "failed"]
    unchanged = sum(1 for d in deltas if d.baseline == "passed" and d.patched == "passed")

    target_before = target_after = None
    if target:
        tb = find_test(baseline.test_run, target) if baseline.test_run else None
        ta = find_test(patched.test_run, target) if patched.test_run else None
        target_before = tb.status if tb else None
        target_after = ta.status if ta else "missing"
    verdict = "verified"
    if patched.timed_out:
        verdict = "rejected"
        reasons.append("Patched test suite timed out")
    if not patched.test_run or not patched.test_run.parse_ok or patched.test_run.total == 0:
        verdict = "rejected"
        reasons.append("Patched test suite produced no parseable results")
    if target and target_after != "passed":
        verdict = "rejected"
        reasons.append(f"Target test does not pass after the patch (status: {target_after})")
    if target and any(r != "passed" for r in repeats):
        verdict = "rejected"
        reasons.append(f"Target test is not stable across isolated re-runs: {repeats}")
    if regressions:
        verdict = "rejected"
        reasons.append(
            f"{len(regressions)} previously passing test(s) regressed: " + "; ".join(regressions[:5])
        )
    if verdict == "verified":
        reasons.append(
            f"Target test passes ({1 + len(repeats)}/{1 + len(repeats)} runs); {len(fixed)} fixed, "
            f"0 regressions, {unchanged} unchanged passing, {len(still_failing)} unrelated still failing"
        )

    def summary(r: ExecutionResult) -> dict[str, int]:
        tr = r.test_run
        return (
            {"total": tr.total, "passed": tr.passed, "failed": tr.failed, "skipped": tr.skipped} if tr else {}
        )

    return VerificationReport(
        verdict=verdict,  # type: ignore[arg-type]
        reasons=reasons,
        target_test=target,
        target_baseline=target_before,
        target_patched=target_after,
        target_repeat_runs=repeats,
        fixed=fixed,
        regressions=regressions,
        still_failing=still_failing,
        unchanged_passing=unchanged,
        baseline_summary=summary(baseline),
        patched_summary=summary(patched),
        deltas=deltas,
        baseline_run=baseline,
        patched_run=patched,
    )


class IndependentVerifier:
    name = "verifier"

    def __init__(self, ctx: InvestigationContext) -> None:
        self.ctx = ctx

    def verify(self, edits: list[SourceEdit], target: str | None, label: str) -> VerificationReport:
        ctx = self.ctx
        assert ctx.report is not None and ctx.report.runtime.runner is not None
        runtime = ctx.report.runtime
        ctx.set_phase(f"verifying {label}", self.name)
        base_ws = ctx.workspaces.create(ctx.snapshot, ctx.investigation_id, f"verify-base-{label}")
        patched_ws = ctx.workspaces.create(ctx.snapshot, ctx.investigation_id, f"verify-patched-{label}")
        try:
            try:
                apply_edits(patched_ws, edits, allow_test_files=False, allow_create=True)
            except EditError as exc:
                return VerificationReport(
                    verdict="rejected",
                    reasons=[f"Patch does not apply to a clean copy: {exc}"],
                    target_test=target,
                    target_baseline=None,
                    target_patched=None,
                )
            baseline = ctx.sandbox.run_tests(base_ws, runtime.runner, runtime.test_targets)
            patched = ctx.sandbox.run_tests(patched_ws, runtime.runner, runtime.test_targets)
            ctx.budget.sandbox_runs += 2
            repeats: list[str] = []
            target_file = ctx.report.target_failure.file if ctx.report.target_failure else None
            if target and target_file and not patched.infra_error:
                for _ in range(TARGET_REPEATS):
                    ctx.checkpoint()
                    rerun = ctx.sandbox.run_tests(
                        patched_ws, runtime.runner, [target_file], isolation_pattern(target)
                    )
                    ctx.budget.sandbox_runs += 1
                    found = find_test(rerun.test_run, target) if rerun.test_run else None
                    repeats.append(found.status if found else ("error" if rerun.infra_error else "missing"))
            report = compare(baseline, patched, target, repeats)
            ctx.emit(
                self.name,
                "verification",
                f"{label}: {report.verdict.upper()} — {report.reasons[0] if report.reasons else ''}",
                {
                    "label": label,
                    "verdict": report.verdict,
                    "fixed": report.fixed,
                    "regressions": report.regressions,
                    "target_patched": report.target_patched,
                    "repeats": repeats,
                    "baseline_summary": report.baseline_summary,
                    "patched_summary": report.patched_summary,
                },
            )
            return report
        finally:
            if not ctx.workspaces_keep:
                ctx.workspaces.discard(base_ws)
                ctx.workspaces.discard(patched_ws)
