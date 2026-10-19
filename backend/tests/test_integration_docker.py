"""Integration tests against the real Docker sandbox (skipped when Docker is unavailable)."""

import json
from pathlib import Path

import pytest

from agents.orchestrator import Orchestrator
from core.config import REPO_ROOT
from core.database import session_scope
from core.models import Investigation, Patch, Repository
from core.schemas import ExperimentFile, SourceEdit
from sandbox.docker import DockerSandbox
from services.repo_analysis import profile_repository
from services.workspace import add_files, apply_edits

pytestmark = pytest.mark.docker

PROBE = """import assert from 'node:assert/strict';
import { it } from 'node:test';
import { writeFileSync } from 'node:fs';

it('has no network access', async () => {
  await assert.rejects(fetch('http://1.1.1.1', { signal: AbortSignal.timeout(3000) }));
});

it('cannot write outside the workspace', () => {
  assert.throws(() => writeFileSync('/usr/local/forge-probe', 'x'));
  assert.throws(() => writeFileSync('/etc/forge-probe', 'x'));
});

it('runs as an unprivileged user', () => {
  assert.equal(process.getuid?.(), 1000);
});

it('does not receive host secrets', () => {
  assert.equal(process.env.META_API_KEY, undefined);
  assert.equal(process.env.DATABASE_URL, undefined);
});
"""


@pytest.fixture(scope="module")
def sandbox():
    return DockerSandbox()


def test_demo_suite_reports_exactly_the_planted_failures(sandbox, demo_copy):
    result = sandbox.run_tests(demo_copy, "node_test", ["test/**/*.test.ts"])
    assert result.infra_error is None
    run = result.test_run
    assert run is not None and run.total == 19
    assert run.failed == 5 and run.passed == 14


def test_sandbox_isolation_guarantees(sandbox, demo_copy):
    add_files(demo_copy, [ExperimentFile(path="test/forge-experiments/probe.test.ts", content=PROBE)])
    result = sandbox.run_tests(demo_copy, "node_test", ["test/forge-experiments/probe.test.ts"])
    assert result.infra_error is None, result.stderr
    failing = [(t.name, t.error) for t in result.test_run.failing()]
    assert not failing, failing
    assert result.sandbox["network"] == "none"


def test_timeout_is_enforced(sandbox, demo_copy):
    add_files(
        demo_copy,
        [
            ExperimentFile(
                path="test/forge-experiments/hang.test.ts",
                content="import { it } from 'node:test';\n"
                "it('hangs', () => new Promise(() => setInterval(() => {}, 1000)));\n",
            )
        ],
    )
    result = sandbox.run_tests(demo_copy, "node_test", ["test/forge-experiments/hang.test.ts"], timeout_s=5)
    assert result.timed_out
    assert result.duration_ms < 40_000


@pytest.mark.parametrize(
    "defect_dir",
    sorted(d for d in (REPO_ROOT / "demo" / "defects").iterdir() if d.is_dir()),
    ids=lambda p: p.name,
)
def test_reference_fix_repairs_its_defect_without_regressions(sandbox, demo_copy, defect_dir: Path):
    defect = json.loads((defect_dir / "defect.json").read_text(encoding="utf-8"))
    fix = json.loads((defect_dir / "reference-fix.json").read_text(encoding="utf-8"))
    apply_edits(demo_copy, [SourceEdit(**e) for e in fix["edits"]], allow_test_files=False, allow_create=True)
    result = sandbox.run_tests(demo_copy, "node_test", ["test/**/*.test.ts"])
    tests = {t.name.split(" > ")[-1]: t.status for t in result.test_run.tests}
    assert tests[defect["failing_test"]["name"]] == "passed"
    for name in defect["regression_tests"]:
        assert tests[name] == "passed", name
    assert result.test_run.failed == 4  # the four other planted defects remain


@pytest.mark.parametrize(
    ("target", "expected_patches"),
    [
        ("checkout > leaves inventory untouched when a multi-item order fails", ["verified"]),
        (
            "payment capture > charges the customer exactly once when a timed-out request is retried",
            ["rejected", "verified"],
        ),
    ],
)
def test_end_to_end_investigation_in_real_sandbox(demo_copy, target, expected_patches):
    with session_scope() as db:
        repo = Repository(
            name="demo",
            source_type="local",
            source=str(demo_copy),
            snapshot_path=str(demo_copy),
            profile=profile_repository(demo_copy),
        )
        db.add(repo)
        db.flush()
        inv = Investigation(repository_id=repo.id, title="e2e", target_test=target, usage={}, budget={})
        db.add(inv)
        db.flush()
        inv_id = inv.id
    Orchestrator(inv_id).run()
    with session_scope() as db:
        inv = db.get(Investigation, inv_id)
        assert inv.status == "completed", inv.error
        assert inv.verdict == "verified_fix"
        patches = db.query(Patch).filter_by(investigation_id=inv_id).order_by(Patch.created_at).all()
        assert [p.status for p in patches] == expected_patches
        if len(patches) > 1:
            assert patches[0].verification["regressions"] == [
                "payment capture > records separate charges for separate capture calls"
            ]
