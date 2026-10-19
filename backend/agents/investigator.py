"""Agent A — Repository Investigator.

Deterministic analysis: static profile, a baseline test run in the sandbox, failure
extraction from the TAP stream, an isolated reproduction run, and collection of the
source files implicated by stack traces and the failing test's import graph.
"""

from __future__ import annotations

import re

from agents.base import AgentError, InvestigationContext, dump
from core.schemas import (
    ExecutionResult,
    FailureObservation,
    InvestigationReport,
    RuntimeProfile,
    TestCaseResult,
)
from sandbox.tap import find_test, leaf_name
from services.repo_analysis import collect_relevant_files, profile_repository
from services.workspace import is_test_path

_FRAME = re.compile(r"/work/(?P<path>[^\s:()]+):(?P<line>\d+)(?::\d+)?")


def stack_frames(test: TestCaseResult) -> list[str]:
    frames = []
    for line in (test.stack or "").splitlines():
        match = _FRAME.search(line)
        if match:
            frames.append(f"{match.group('path')}:{match.group('line')}  ({line.strip()[:160]})")
    return frames


def implicated_files(test: TestCaseResult) -> list[str]:
    paths: list[str] = []
    for line in (test.stack or "").splitlines():
        match = _FRAME.search(line)
        if match and match.group("path") not in paths:
            paths.append(match.group("path"))
    if test.file and test.file not in paths:
        paths.append(test.file)
    return sorted(paths, key=is_test_path)


def observe(test: TestCaseResult) -> FailureObservation:
    return FailureObservation(
        test_name=test.name,
        file=test.file,
        error=test.error,
        error_name=test.error_name,
        failure_type=test.failure_type,
        stack_frames=stack_frames(test),
        implicated_files=implicated_files(test),
    )


def isolation_pattern(test_name: str) -> str:
    return f"^{re.escape(leaf_name(test_name))}$"


class RepositoryInvestigator:
    name = "investigator"

    def __init__(self, ctx: InvestigationContext) -> None:
        self.ctx = ctx

    def run_suite(self, runtime: RuntimeProfile, label: str) -> ExecutionResult:
        ctx = self.ctx
        assert runtime.runner is not None
        result = ctx.sandbox.run_tests(ctx.snapshot, runtime.runner, runtime.test_targets)
        ctx.budget.sandbox_runs += 1
        tr = result.test_run
        ctx.emit(
            self.name,
            "sandbox_run",
            f"{label}: exit {result.exit_code}, "
            + (f"{tr.passed} passed / {tr.failed} failed of {tr.total}" if tr else "no test report")
            + f" in {result.duration_ms} ms",
            {
                "label": label,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "command": result.command,
                "image": result.image,
                "sandbox": result.sandbox,
                "infra_error": result.infra_error,
                "summary": {"total": tr.total, "passed": tr.passed, "failed": tr.failed} if tr else None,
                "stdout_tail": result.stdout[-4000:],
            },
        )
        return result

    def run(self) -> tuple[InvestigationReport, ExecutionResult | None]:
        """Returns the report and the isolated reproduction run (if one was executed)."""
        ctx = self.ctx
        ctx.set_phase("investigating", self.name)
        profile = profile_repository(ctx.snapshot)
        runtime = RuntimeProfile.model_validate(profile["runtime"])
        ctx.emit(
            self.name,
            "analysis",
            f"Profiled {profile['file_count']} files: "
            + ", ".join(f"{k} ({v})" for k, v in list(profile["languages"].items())[:4])
            + f"; runtime {runtime.runtime}, runner {runtime.runner}",
            {"profile": {k: v for k, v in profile.items() if k not in ("source_files", "test_files")}},
        )
        report = InvestigationReport(
            repository=ctx.repository_name,
            file_count=profile["file_count"],
            languages=profile["languages"],
            frameworks=profile["frameworks"],
            package_manager=profile["package_manager"],
            dependencies=profile["dependencies"],
            source_files=profile["source_files"],
            test_files=profile["test_files"],
            runtime=runtime,
            notes=list(runtime.notes),
        )
        if runtime.runner is None or not runtime.test_targets:
            report.notes.append("No supported test runner or test files were found; cannot observe failures.")
            return report, None

        baseline = self.run_suite(runtime, "Baseline test suite")
        report.baseline = baseline
        if baseline.infra_error:
            raise AgentError(f"Sandbox execution failed: {baseline.infra_error}")
        if baseline.timed_out:
            report.notes.append("Baseline test run timed out.")
        test_run = baseline.test_run
        if test_run is None or not test_run.parse_ok:
            raise AgentError("Could not parse a test report from the baseline run")
        report.observed_failures = [observe(t) for t in test_run.failing()]

        target: TestCaseResult | None = None
        if ctx.target_test:
            target = find_test(test_run, ctx.target_test)
            if target is None:
                report.notes.append(
                    f"Requested target test {ctx.target_test!r} was not found in the baseline run."
                )
            elif target.status != "failed":
                report.notes.append(f"Requested target test {ctx.target_test!r} {target.status} at baseline.")
                target = None
        elif test_run.failing():
            target = test_run.failing()[0]
        if target is None:
            return report, None
        report.target_failure = observe(target)
        ctx.emit(
            self.name,
            "failure_observed",
            f"Target failure: {target.name} ({target.error_name}: {(target.error or '')[:120]})",
            {"failure": dump(report.target_failure), "other_failures": len(report.observed_failures) - 1},
        )

        reproduction = None
        if target.file:
            reproduction = ctx.sandbox.run_tests(
                ctx.snapshot, runtime.runner, [target.file], isolation_pattern(target.name)
            )
            ctx.budget.sandbox_runs += 1
            rerun = find_test(reproduction.test_run, target.name) if reproduction.test_run else None
            report.reproduction_confirmed = bool(rerun and rerun.status == "failed")
            ctx.emit(
                self.name,
                "reproduction",
                "Target failure reproduced in isolation"
                if report.reproduction_confirmed
                else "Target failure did NOT reproduce in isolation (order-dependent or flaky)",
                {"reproduced": report.reproduction_confirmed, "duration_ms": reproduction.duration_ms},
            )

        seeds = [
            (f, "in failing stack trace")
            for f in report.target_failure.implicated_files
            if not is_test_path(f)
        ]
        if target.file:
            seeds.insert(0, (target.file, "failing test file"))
        report.relevant_files = collect_relevant_files(ctx.snapshot, seeds)
        ctx.emit(
            self.name,
            "context_collected",
            f"Collected {len(report.relevant_files)} relevant files",
            {"files": [{"path": f.path, "reason": f.reason} for f in report.relevant_files]},
        )
        return report, reproduction
