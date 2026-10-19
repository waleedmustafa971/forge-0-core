# FORGE-0 — Hackathon submission draft

**Event:** Meta Global AI Developer Hackathon 2026 · **Theme:** Push the Frontier · **Track:** Indie Developer

## One-liner

FORGE-0 is an autonomous debugger that refuses to guess: it proposes competing root-cause
hypotheses, runs counterfactual experiments in an isolated sandbox to rule them out, and only
offers a repair after an independent verifier has proven it fixes the bug without breaking anything.

## The problem

AI coding assistants are confident patch generators. They read a stack trace, pick the first
plausible story, and emit a diff. When that story is wrong, the patch looks right, sometimes even
makes the failing test pass, and quietly breaks something else. Developers end up verifying the AI
instead of the code.

## What FORGE-0 does differently

1. **Competing hypotheses, not a single guess.** Every investigation starts with at least two
   mutually exclusive explanations, each with a prior.
2. **Experiments with predictions.** For each experiment, every hypothesis must say in advance
   whether it will pass or fail. That includes *counterfactual interventions*: "if `reserve` used
   the transaction handle, would the original failure disappear?", executed on a disposable copy.
3. **Bayesian bookkeeping.** Observed outcomes update the ranking. Hypotheses are refuted by
   evidence, and confirmation requires a *discriminating* experiment.
4. **Independent verification.** Patches are re-applied to fresh copies; the whole suite runs before
   and after; the target is re-run in isolation. Any regression rejects the patch, and the reasons go
   back to the Repair Engineer.
5. **A full audit trail.** Every hypothesis, prediction, execution, belief update and decision is
   persisted and streamed live to the dashboard, then compiled into an evidence report for human
   review. FORGE-0 never applies a patch to your code.

## Why Muse Spark

FORGE-0's model-facing work is structured reasoning under uncertainty: generating rival
explanations, designing tests that separate them, and writing minimal patches that respect the
evidence. The integration targets `muse-spark-1.3` on the Meta Model API with JSON-schema
structured outputs, configurable `reasoning_effort`, and the documented `max_completion_tokens`
contract. Every model contract is a Pydantic schema, so the same prompts and validators work
unchanged when the key is added.

## What is built (and verified)

* Seven-agent pipeline (Investigator, Hypothesis Generator, Experiment Designer, Executor, Repair
  Engineer, Independent Verifier, Orchestrator) with budgets for time, model calls, experiments,
  rounds and repair attempts.
* Hardened Docker sandbox: no network, read-only root filesystem, tmpfs workspace streamed over
  stdin (no host mounts), non-root, capabilities dropped, CPU/memory/PID/file limits, dual
  timeouts, allowlisted runners only. Isolation is verified by integration tests.
* FastAPI backend, PostgreSQL + Alembic, Server-Sent Events, Markdown/JSON evidence reports.
* React dashboard: live agent pipeline, hypotheses with confidence history, experiment timeline with
  predictions vs observations, patch review with test-by-test deltas, evaluation page, settings.
* A TypeScript order-management service with five planted defects (concurrency, retries,
  transactions, async errors, validation), reference fixes and hidden tests kept away from agents.
* An evaluation harness comparing a one-shot baseline with FORGE-0, scored by hidden tests.
* 75 backend tests (incl. 11 against real Docker/PostgreSQL), 9 frontend tests, CI with lint,
  type checks, builds, integration tests, gitleaks and dependency audits.

## Honest status

* **No real Muse Spark inference has run yet.** API access was not available during the build. All
  demo runs use the mock provider, whose outputs are scripted fixtures and are labelled *simulated*
  in the UI, API and reports. Executions and verifications are real.
* The baseline-vs-FORGE-0 numbers in `docs/EVALUATION.md` come from that mock run. They validate the
  pipeline, not model capability. The real comparison is one command away once a key is configured.
* The sandbox currently supports Node.js projects (Python runner provided, less tested); dependency
  installation inside the offline sandbox is not supported.

## Demo video script (≈2:45)

| Time | Screen | Narration |
| --- | --- | --- |
| 0:00–0:15 | Dashboard | "AI assistants write patches fast, and they're often confidently wrong. FORGE-0 is a debugger that has to *prove* its fix before you ever see it." |
| 0:15–0:35 | Repository Explorer → Run in sandbox | "Here's an order-management service with five real-world defects. FORGE-0 runs its suite in a locked-down container with no network, read-only, non-root: 14 pass, 5 fail." |
| 0:35–0:55 | Start investigation (concurrency defect) | "Let's investigate the lost-update bug. First the investigator reproduces the failure in isolation. Then the model proposes three competing explanations: a race, storage aliasing, or a logic error." |
| 0:55–1:30 | Workspace: experiments + confidence bars | "Each experiment states in advance what each hypothesis predicts. Sequential additions pass: the logic-error theory is refuted. The database isolates rows: aliasing is refuted. Then a counterfactual: serialize `addItem` in a throw-away copy, and the failure vanishes. The race hypothesis is confirmed at 96%." |
| 1:30–1:50 | Patch review | "Only now does it write a patch: a per-order mutex. An independent verifier re-runs the whole suite on fresh copies. Target fixed three out of three times, zero regressions." |
| 1:50–2:15 | Payment investigation, rejected P1 | "Here's why verification matters. On the double-charge bug, the first patch fixes the failing test but breaks separate captures for the same order. The verifier rejects it and feeds that back, and the second patch is accepted." |
| 2:15–2:35 | Evaluation page | "Against a one-shot baseline, FORGE-0 never claims a fix it can't prove. These numbers come from our scripted mock run, clearly labelled; with a Muse Spark key, the same harness measures the real thing." |
| 2:35–2:45 | Settings → Meta Model API | "Muse Spark plugs in with one environment variable. FORGE-0: scientific debugging, with receipts." |

## Links

* Repository: private GitHub repository `forge-0` (shared with judges on request)
* Architecture: `docs/ARCHITECTURE.md` · Security: `docs/SECURITY.md` · Evaluation: `docs/EVALUATION.md`
