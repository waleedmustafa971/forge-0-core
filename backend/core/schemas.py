"""Structured contracts exchanged between FORGE-0 agents.

Every model-facing contract (``*Draft`` / ``*Set`` / ``*Plan``) is what a provider must
return; everything else is produced deterministically by the system itself.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Execution evidence (produced by the sandbox, never by a model)
# ---------------------------------------------------------------------------

TestStatus = Literal["passed", "failed", "skipped", "todo"]


class TestCaseResult(BaseModel):
    name: str
    file: str | None = None
    status: TestStatus
    duration_ms: float | None = None
    failure_type: str | None = None
    error: str | None = None
    error_name: str | None = None
    error_code: str | None = None
    stack: str | None = None
    location: str | None = None


class TestRunSummary(BaseModel):
    tests: list[TestCaseResult] = Field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    parse_ok: bool = True

    def by_name(self) -> dict[str, TestCaseResult]:
        return {t.name: t for t in self.tests}

    def failing(self) -> list[TestCaseResult]:
        return [t for t in self.tests if t.status == "failed"]


class ExecutionResult(BaseModel):
    runner: str
    image: str
    command: list[str]
    exit_code: int | None
    timed_out: bool = False
    duration_ms: int
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    infra_error: str | None = None
    sandbox: dict[str, str | int | float | bool] = Field(default_factory=dict)
    test_run: TestRunSummary | None = None


# ---------------------------------------------------------------------------
# Agent A — Repository Investigator
# ---------------------------------------------------------------------------


class FileExcerpt(BaseModel):
    path: str
    content: str
    truncated: bool = False
    reason: str = ""


class FailureObservation(BaseModel):
    test_name: str
    file: str | None = None
    error: str | None = None
    error_name: str | None = None
    failure_type: str | None = None
    stack_frames: list[str] = Field(default_factory=list)
    implicated_files: list[str] = Field(default_factory=list)


class RuntimeProfile(BaseModel):
    runtime: Literal["node", "python", "unknown"]
    runner: str | None
    test_targets: list[str] = Field(default_factory=list)
    image: str | None = None
    notes: list[str] = Field(default_factory=list)


class InvestigationReport(BaseModel):
    repository: str
    file_count: int
    languages: dict[str, int]
    frameworks: list[str]
    package_manager: str | None
    dependencies: dict[str, str]
    source_files: list[str]
    test_files: list[str]
    runtime: RuntimeProfile
    baseline: ExecutionResult | None = None
    observed_failures: list[FailureObservation] = Field(default_factory=list)
    target_failure: FailureObservation | None = None
    reproduction_confirmed: bool | None = None
    relevant_files: list[FileExcerpt] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Model-facing contracts
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore")


class HypothesisDraft(_Strict):
    key: str = Field(description="Short identifier such as H1, H2")
    title: str = Field(description="One-line statement of the suspected root cause")
    explanation: str = Field(description="Mechanism: how this cause produces the observed failure")
    suspected_locations: list[str] = Field(default_factory=list, description="file or file:line")
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    prior: float = Field(ge=0.0, le=1.0, description="Prior probability before experiments")


class HypothesisSet(_Strict):
    reasoning_summary: str
    hypotheses: list[HypothesisDraft]


class ExperimentFile(_Strict):
    path: str = Field(description="New file path relative to the repository root")
    content: str


class SourceEdit(_Strict):
    file: str = Field(description="Existing file path relative to the repository root")
    search: str = Field(description="Exact text to replace; must occur exactly once")
    replace: str


class Prediction(_Strict):
    hypothesis: str
    outcome: Literal["pass", "fail"]
    output_contains: str | None = Field(
        default=None, description="Optional substring expected in the test output if the hypothesis holds"
    )
    rationale: str = ""


class ExperimentDraft(_Strict):
    key: str
    objective: str
    kind: Literal["reproduction", "discrimination", "intervention"]
    hypotheses: list[str]
    files: list[ExperimentFile] = Field(default_factory=list)
    source_edits: list[SourceEdit] = Field(
        default_factory=list, description="Counterfactual interventions applied only in the experiment copy"
    )
    run: list[str] = Field(description="Test files to execute, relative to the repository root")
    test_name_pattern: str | None = None
    predictions: list[Prediction]
    success_condition: str
    failure_condition: str


class ExperimentPlan(_Strict):
    rationale: str
    experiments: list[ExperimentDraft]
    conclude: bool = Field(default=False, description="True when no further experiment is informative")


class PatchDraft(_Strict):
    hypothesis: str
    summary: str
    rationale: str
    edits: list[SourceEdit]
    risk_notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent F — Independent Verifier
# ---------------------------------------------------------------------------


class TestDelta(BaseModel):
    name: str
    baseline: str | None
    patched: str | None


class VerificationReport(BaseModel):
    verdict: Literal["verified", "rejected", "error"]
    reasons: list[str]
    target_test: str | None
    target_baseline: str | None
    target_patched: str | None
    target_repeat_runs: list[str] = Field(default_factory=list)
    fixed: list[str] = Field(default_factory=list)
    regressions: list[str] = Field(default_factory=list)
    still_failing: list[str] = Field(default_factory=list)
    unchanged_passing: int = 0
    baseline_summary: dict[str, int] = Field(default_factory=dict)
    patched_summary: dict[str, int] = Field(default_factory=dict)
    deltas: list[TestDelta] = Field(default_factory=list)
    baseline_run: ExecutionResult | None = None
    patched_run: ExecutionResult | None = None
