# Evaluation methodology

## Question

Does hypothesis-driven, experiment-backed debugging (System B, FORGE-0) produce more *real* fixes
and fewer *false* fix claims than asking a model for a patch directly (Baseline A), and at what cost?

## Systems

| | Baseline A · direct one-shot repair | System B · FORGE-0 |
| --- | --- | --- |
| Context | Same Investigator report: failing test output, stack frames, relevant files | Same |
| Hypotheses | none | ≥2 competing, with priors |
| Experiments | none | discriminating probes and counterfactual interventions in the sandbox |
| Patch | one model call | Repair Engineer, up to `MAX_REPAIR_ATTEMPTS`, with verifier feedback |
| Claims a fix when | it produces a patch | the Independent Verifier accepts a patch |

Both run through the same orchestrator, sandbox and provider. The Independent Verifier also runs
after Baseline A, but only to *measure* it — its result does not feed back.

## Dataset

Five planted defects in `demo/order-management` (catalog: `demo/defects/`):

| Id | Category | Symptom |
| --- | --- | --- |
| D1-lost-update | concurrency | concurrent `addItem` calls lose items |
| D2-duplicate-charge | retries / idempotency | a retried capture charges twice |
| D3-transaction-leak | DB transactions | a failed checkout leaks stock reservations |
| D4-unhandled-async-error | async error handling | carrier failures bypass `try/catch` |
| D5-terminal-status | validation | cancelled orders can be paid/shipped |

Each defect has a failing test, regression tests that pass before the fix, a reference fix and
**hidden tests** (`benchmarks/hidden-tests/`) that neither system ever sees. The integration suite
proves every reference fix passes its target, regression and hidden tests without breaking anything
(`backend/tests/test_integration_docker.py`).

## Independent evaluation

For each claimed patch, the harness (`benchmarks/run_benchmark.py`) takes a fresh copy of the
repository, applies the patch, adds the defect's hidden tests and runs the whole suite in the
sandbox. A defect counts as **actually fixed** only if the target test passes, every hidden test
passes and no previously passing test regresses.

## Metrics

| Metric | Definition |
| --- | --- |
| Reproduction success rate | target failure re-observed in an isolated re-run |
| Verified repair rate | actually fixed / defects |
| False-positive repair rate | claimed but not actually fixed / claimed |
| Regression failures | claimed fixes that break a previously passing test |
| Experiments | sandbox experiments executed (excludes the E0 control run) |
| Execution time | wall-clock per investigation |
| Token usage | `usage` reported by the provider (estimated for mock) |
| Estimated API cost | tokens × configured list price (Muse Spark 1.3 standard: $1.25 / $4.25 per 1M) |

## Running

Runs are described by JSON configs in `benchmarks/configs/`:

| Config | Provider | Defects × systems × repeats | Guards |
| --- | --- | --- | --- |
| `mock.json` (default) | mock (scripted) | 5 × 2 × 1 | results are labelled SIMULATED |
| `muse-spark-1.3.json` | Meta, `muse-spark-1.3`, `reasoning_effort=medium`, 8,192 max tokens | 5 × 2 × 3 | refuses the mock fallback (exit 3); worst-case cost printed and capped at $25; requires `--yes` |

```powershell
backend\.venv\Scripts\python benchmarks\run_benchmark.py                                   # mock
backend\.venv\Scripts\python benchmarks\run_benchmark.py --config benchmarks\configs\muse-spark-1.3.json --dry-run
backend\.venv\Scripts\python benchmarks\run_benchmark.py --config benchmarks\configs\muse-spark-1.3.json --yes
backend\.venv\Scripts\python benchmarks\run_benchmark.py --defects D2-duplicate-charge --repeats 2   # overrides
```

`--dry-run` validates the config, the sandbox and provider connectivity (`GET /models`, no tokens)
and prints the worst-case cost. That estimate assumes every call uses the full model-call budget,
a schema-repair round, 10k prompt tokens and the full output limit. Three repeats are used for real
models because their output is stochastic; report per-defect success counts (`per_defect` in the
results), failed model calls and token usage.

Results: `benchmarks/results/<run_id>.json` (raw) and `.html` (visual report); also shown on the
dashboard's **Evaluation** page.

## Current results — mock only

> **These numbers are NOT evidence of model capability.** The only completed run used the mock
> provider, whose outputs are fixtures authored for this demo. Baseline A was given each
> scenario's scripted "first idea" patch; for D1 and D2 that first idea is plausible but wrong by
> design, to show what verification catches. The sandbox runs, the verifier and the hidden-test
> evaluation are real executions. No real-model evaluation has been run yet (no API key).

Run `20261019-073640-mock` (`benchmarks/results/20261019-073640-mock.json`); a second run with the
rewritten harness (`20261019-085242-mock`) reproduced the same outcomes and token counts:

| Metric | Baseline A | System B |
| --- | --- | --- |
| Reproduction success rate | 100% | 100% |
| Verified repair rate (hidden-test confirmed) | 60% (3/5) | 100% (5/5) |
| False-positive repair rate | 40% (2/5 claims) | 0% (0/5 claims) |
| Claimed fixes with regressions | 1 | 0 |
| Mean experiments per defect | 0 | 3 |
| Total wall time | 91.6 s | 115.2 s |
| Model calls | 5 | 16 |
| Tokens (estimated) | 31,253 | 115,506 |
| Estimated cost at list price (hypothetical) | $0.041 | $0.169 |

What this run *does* validate: the whole pipeline executes end to end on five defect classes; the
verifier catches a wrong patch that leaves the target failing (D1 baseline) and a patch that fixes
the target but breaks `records separate charges for separate capture calls` (D2 — both the
baseline and System B's first attempt, which System B then revised); hidden tests agree with the
verifier on every verified patch; and evidence costs roughly 3.7× the tokens of a one-shot repair.

## Threats to validity

* Five small, synthetic defects in one TypeScript service; the defects were written alongside the
  system that solves them.
* The mock comparison is constructed; only a real-model run measures the method.
* Single run per configuration; real models are stochastic — repeat runs (`n ≥ 5`) are needed for
  rates with confidence intervals.
* The hidden tests are stricter than the visible tests but not exhaustive.
