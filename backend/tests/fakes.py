"""A scripted sandbox for exercising orchestration logic without Docker.

It inspects the workspace it is given (exactly like the real sandbox would receive it)
and synthesises the TAP stream node would print for the demo suite, so the orchestrator,
belief updates and verifier run unmodified.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.schemas import ExecutionResult
from sandbox.docker import SandboxStatus
from sandbox.tap import parse_tap

TARGET = "order status lifecycle > does not allow a cancelled order to be paid or shipped"
SUITE = [
    ("order status lifecycle", "allows the standard happy path", "test/status.test.ts"),
    ("order status lifecycle", "rejects moving a shipped order back to pending", "test/status.test.ts"),
    ("order status lifecycle", "treats re-applying the current status as a no-op", "test/status.test.ts"),
    (
        "order status lifecycle",
        "does not allow a cancelled order to be paid or shipped",
        "test/status.test.ts",
    ),
    ("payment capture", "records separate charges for separate capture calls", "test/payments.test.ts"),
]


def tap(results: list[tuple[str | None, str, str, bool, str]]) -> str:
    """results: (suite, name, file, passed, error)."""
    lines = ["TAP version 13"]
    by_suite: dict[str | None, list[tuple[str, str, bool, str]]] = {}
    for suite, name, file, passed, error in results:
        by_suite.setdefault(suite, []).append((name, file, passed, error))
    for s_index, (suite, tests) in enumerate(by_suite.items(), start=1):
        indent = "    " if suite else ""
        if suite:
            lines.append(f"# Subtest: {suite}")
        for t_index, (name, file, passed, error) in enumerate(tests, start=1):
            lines.append(f"{indent}# Subtest: {name}")
            lines.append(f"{indent}{'ok' if passed else 'not ok'} {t_index} - {name}")
            lines.append(f"{indent}  ---")
            lines.append(f"{indent}  duration_ms: 1.5")
            lines.append(f"{indent}  type: 'test'")
            if not passed:
                lines.append(f"{indent}  location: '/work/{file}:10:3'")
                lines.append(f"{indent}  failureType: 'testCodeFailure'")
                lines.append(f"{indent}  error: '{error}'")
                lines.append(f"{indent}  code: 'ERR_ASSERTION'")
                lines.append(f"{indent}  name: 'AssertionError'")
                lines.append(f"{indent}  stack: |-")
                lines.append(f"{indent}    TestContext.<anonymous> (file:///work/{file}:12:5)")
                lines.append(f"{indent}    canTransition (file:///work/src/domain/status.ts:20:3)")
            lines.append(f"{indent}  ...")
        if suite:
            all_ok = all(t[2] for t in tests)
            lines.append(f"{indent}1..{len(tests)}")
            lines.append(f"{'ok' if all_ok else 'not ok'} {s_index} - {suite}")
            lines.append("  ---")
            lines.append("  type: 'suite'")
            lines.append("  ...")
    lines.append(f"1..{len(by_suite)}")
    return "\n".join(lines) + "\n"


@dataclass
class Call:
    workspace: Path
    runner: str
    targets: list[str]
    pattern: str | None


class FakeSandbox:
    docker = ["fake-docker"]

    def __init__(self, *, available: bool = True, break_regression: bool = False) -> None:
        self.available = available
        self.break_regression = break_regression
        self.calls: list[Call] = []

    def status(self, refresh: bool = False) -> SandboxStatus:  # noqa: ARG002
        return SandboxStatus(self.available, "fake sandbox", self.docker, "fake")

    def run_tests(self, workspace, runner_name, targets, test_name_pattern=None, timeout_s=None):  # noqa: ARG002
        self.calls.append(Call(Path(workspace), runner_name, list(targets), test_name_pattern))
        if not self.available:
            return ExecutionResult(
                runner=runner_name,
                image="fake",
                command=[],
                exit_code=None,
                duration_ms=1,
                infra_error="unavailable",
            )
        status_src = (Path(workspace) / "src/domain/status.ts").read_text(encoding="utf-8")
        fixed = "allowed.length === 0 ||" not in status_src
        results: list[tuple[str | None, str, str, bool, str]] = []
        if any("forge-experiments" in t for t in targets):
            target = targets[0]
            if "E1-rule" in target:
                results.append(
                    (None, "terminal statuses reject outgoing transitions", target, fixed, "true !== false")
                )
            else:
                results.append((None, f"probe {target}", target, True, ""))
        else:
            for suite, name, file in SUITE:
                full = f"{suite} > {name}"
                if test_name_pattern and name not in test_name_pattern.replace("\\", ""):
                    continue
                passed = full != TARGET or fixed
                if self.break_regression and fixed and "separate charges" in name:
                    passed = False
                results.append(
                    (suite, name, file, passed, "Missing expected rejection (InvalidTransitionError).")
                )
        stdout = tap(results)
        run = parse_tap(stdout)
        return ExecutionResult(
            runner=runner_name,
            image="fake",
            command=["node", "--test", *targets],
            exit_code=1 if run.failed else 0,
            duration_ms=5,
            stdout=stdout,
            test_run=run,
        )
