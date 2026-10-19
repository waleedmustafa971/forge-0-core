"""Prompt templates for model-backed agents (B, C, E and the Baseline A one-shot repair)."""

from __future__ import annotations

import json
from typing import Any

from core.schemas import FileExcerpt, InvestigationReport

SCIENTIFIC_PREAMBLE = (
    "You are part of FORGE-0, an evidence-driven debugging system. Claims are only accepted when "
    "executed experiments support them. Never claim a defect is fixed; an independent verifier decides "
    "that by running tests. Be precise and concise."
)


def runtime_contract(report: InvestigationReport) -> str:
    if report.runtime.runtime == "node":
        return (
            "Experiment runtime contract (Node.js, executed in an offline sandbox):\n"
            "- Tests use the built-in runner: `import { it, describe } from 'node:test'` and "
            "`import assert from 'node:assert/strict'`.\n"
            "- TypeScript runs through Node's type stripping: only erasable syntax (no enums, namespaces or "
            "constructor parameter properties); use `import type` for type-only imports; relative imports must "
            "include the `.ts` extension.\n"
            "- Put new experiment files under `test/forge-experiments/` (e.g. `test/forge-experiments/E1-name.test.ts`); "
            "from there, source files are imported as `../../src/...` and existing helpers as `../helpers.ts`.\n"
            "- No network access, no package installs, 60 second timeout, no dependencies beyond the repository.\n"
            "- `run` lists the test files to execute; `test_name_pattern` optionally filters test names (regex).\n"
            "- An outcome is `fail` if any executed test fails and `pass` if all executed tests pass."
        )
    return (
        "Experiment runtime contract (Python, executed in an offline sandbox with pytest):\n"
        "- Put new experiment files under `tests/forge_experiments/test_<name>.py`.\n"
        "- `run` lists test files; `test_name_pattern` is passed to `pytest -k`."
    )


def _files_block(files: list[FileExcerpt]) -> str:
    parts = []
    for f in files:
        note = " (truncated)" if f.truncated else ""
        parts.append(f"### {f.path}{note} — {f.reason}\n```\n{f.content}\n```")
    return "\n\n".join(parts)


def _failure_block(report: InvestigationReport) -> str:
    target = report.target_failure
    if target is None:
        return "No failing test was observed."
    others = [f.test_name for f in report.observed_failures if f.test_name != target.test_name]
    lines = [
        f"Target failure: `{target.test_name}` in `{target.file}`",
        f"Error type: {target.error_name} ({target.failure_type})",
        f"Error message:\n```\n{target.error}\n```",
    ]
    if target.stack_frames:
        lines.append(
            "Stack frames inside the repository:\n" + "\n".join(f"- {s}" for s in target.stack_frames[:12])
        )
    if report.reproduction_confirmed is not None:
        lines.append(
            "Isolated re-run of the target test: "
            + (
                "failed again (reproducible)"
                if report.reproduction_confirmed
                else "PASSED (not reproducible in isolation)"
            )
        )
    if others:
        lines.append(
            "Other failing tests (out of scope for this investigation):\n"
            + "\n".join(f"- {o}" for o in others)
        )
    return "\n".join(lines)


def repo_summary(report: InvestigationReport) -> str:
    base = report.baseline.test_run if report.baseline else None
    counts = f"{base.passed} passed, {base.failed} failed of {base.total}" if base else "not executed"
    return (
        f"Repository: {report.repository} ({report.file_count} files)\n"
        f"Languages: {json.dumps(report.languages)}\n"
        f"Frameworks: {', '.join(report.frameworks) or 'none detected'}\n"
        f"Baseline test run: {counts}"
    )


def hypotheses_prompt(report: InvestigationReport, symptom: str) -> tuple[str, str]:
    system = (
        f"{SCIENTIFIC_PREAMBLE}\nRole: Hypothesis Generator. Produce 2-4 *competing*, mutually exclusive "
        "root-cause hypotheses for the target failure. Each must name a concrete mechanism and location, list "
        "the evidence that supports it and anything that contradicts it, and carry a prior probability. "
        "Prefer hypotheses that a cheap experiment could falsify. Do not propose fixes."
    )
    user = "\n\n".join(
        [
            repo_summary(report),
            f"Reported symptom: {symptom or '(none provided; use the failing test)'}",
            _failure_block(report),
            "Relevant source files:\n\n" + _files_block(report.relevant_files),
        ]
    )
    return system, user


def experiments_prompt(
    report: InvestigationReport,
    hypotheses: list[dict[str, Any]],
    history: list[dict[str, Any]],
    remaining: int,
    round_index: int,
) -> tuple[str, str]:
    system = (
        f"{SCIENTIFIC_PREAMBLE}\nRole: Experiment Designer. Design at most {remaining} experiments that "
        "DISCRIMINATE between the open hypotheses: for each experiment, every listed hypothesis must make a "
        "prediction (pass or fail, optionally an output substring), and at least two hypotheses must predict "
        "different results. Prefer small targeted tests. Use `source_edits` for counterfactual interventions "
        "(e.g. 'if this line used the transaction handle, would the failure disappear?'); they are applied only "
        "to a disposable copy and never to the repository. Never edit existing test files. If no further "
        "experiment would be informative, return an empty list and set conclude=true.\n\n"
        + runtime_contract(report)
    )
    user = "\n\n".join(
        [
            repo_summary(report),
            _failure_block(report),
            f"Experiment round: {round_index + 1}",
            "Current hypotheses and confidence:\n```json\n" + json.dumps(hypotheses, indent=2) + "\n```",
            "Experiments already executed:\n```json\n" + json.dumps(history, indent=2) + "\n```"
            if history
            else "No experiments executed yet.",
            "Relevant source files:\n\n" + _files_block(report.relevant_files),
        ]
    )
    return system, user


def repair_prompt(
    report: InvestigationReport,
    leader: dict[str, Any],
    evidence: list[dict[str, Any]],
    previous_attempts: list[dict[str, Any]],
) -> tuple[str, str]:
    system = (
        f"{SCIENTIFIC_PREAMBLE}\nRole: Repair Engineer. Write the smallest source change that removes the root "
        "cause established by the evidence, preserving all unrelated behaviour. Express it as search/replace "
        "edits: `search` must be copied exactly from the current file and occur exactly once; to create a new "
        "file use an empty `search`. Test files may not be modified. Explain the reasoning and list risks. If a "
        "previous attempt was rejected, address the verifier's findings explicitly."
    )
    user = "\n\n".join(
        [
            repo_summary(report),
            _failure_block(report),
            "Leading hypothesis:\n```json\n" + json.dumps(leader, indent=2) + "\n```",
            "Experimental evidence:\n```json\n" + json.dumps(evidence, indent=2) + "\n```",
            "Previous rejected attempts:\n```json\n" + json.dumps(previous_attempts, indent=2) + "\n```"
            if previous_attempts
            else "This is the first repair attempt.",
            "Relevant source files:\n\n" + _files_block(report.relevant_files),
        ]
    )
    return system, user


def one_shot_prompt(report: InvestigationReport, symptom: str) -> tuple[str, str]:
    system = (
        "You are a software engineer. Fix the failing test by editing source code. Express the fix as "
        "search/replace edits: `search` must be copied exactly from the current file and occur exactly once. "
        'Test files may not be modified. Set `hypothesis` to "direct".'
    )
    user = "\n\n".join(
        [
            repo_summary(report),
            f"Reported symptom: {symptom or '(none)'}",
            _failure_block(report),
            "Relevant source files:\n\n" + _files_block(report.relevant_files),
        ]
    )
    return system, user
