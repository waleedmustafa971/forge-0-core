# Project status and handoff

**As of 2026-10-19.** FORGE-0 is feature-complete in mock mode and **waiting for Meta Model API
access** (Muse Spark) for its first real-model evaluation. All backend processes are stopped; the
code is on `main` in the private repository <https://github.com/waleedmustafa971/forge-0> and CI is
green.

## What works (verified)

| Area | Evidence |
| --- | --- |
| End-to-end investigations on all 5 demo defects | Mock benchmark runs `20261019-073640-mock` and `20261019-085242-mock` (identical results). |
| Double-charge demo: reproduce → reject regressing patch → verify revised patch | `scripts/audit_demo.py`: 17/17 checks |
| Docker sandbox isolation (no network, read-only root, uid 1000, no secrets, timeouts) | `backend/tests/test_integration_docker.py`, run in CI on GitHub-hosted runners |
| PostgreSQL migrations `0001` → `0002` (upgrade/downgrade) | `backend/tests/test_postgres.py`, run in CI |
| Meta provider request/response handling | `backend/tests/test_meta_contract.py`, against the documented contract with a mock transport |
| Lite mode and memory reduction | [OPERATIONS.md](OPERATIONS.md) |
| Containerised full stack (`docker compose --profile app`) | Built and exercised on 2026-10-19: one investigation through nginx and the containerised backend ended `verified_fix` |

### Test and CI results

| Suite | Result |
| --- | --- |
| Backend unit + API (`pytest -m "not docker and not postgres"`) | 90 passed |
| Backend integration (real Docker + PostgreSQL) | 11 passed |
| Frontend (`npm test`) | 9 passed |
| Lint/format/types (ruff incl. `benchmarks/` and `scripts/`, eslint, tsc, demo tsc) | clean |
| GitHub Actions run 39240489515 (commit `0b37cc7`) | all jobs succeeded. gitleaks: 12 commits, no leaks; pip-audit and npm audit: no known vulnerabilities |

## What is NOT established yet

* **No real model has been run.** Every investigation and benchmark so far used the mock provider,
  whose hypotheses, experiments and patches are scripted fixtures. Execution and verification results
  are real; *model performance is unknown*. The mock benchmark (Baseline A 3/5 fixed with 2 false
  positives, FORGE-0 5/5 with none) reflects fixture authoring and must not be cited as AI repair
  performance.
* The Meta provider has not talked to `api.meta.ai` (no key).
* Python repositories (pytest runner) are experimental.

## When the Meta API key arrives

1. Add the key to `.env` (git-ignored; never commit it):

   ```dotenv
   META_API_KEY=<key>
   ```

2. Start FORGE-0 and check connectivity (step 2a uses no tokens; 2b makes one small structured request):

   ```powershell
   .\scripts\lite.ps1 start
   backend\.venv\Scripts\python scripts\check_meta.py                # 2a: GET /models
   backend\.venv\Scripts\python scripts\check_meta.py --structured   # 2b: one structured request
   ```

3. Try one investigation by hand. In **Settings**, choose *Meta Model API*, save, then start the
   double-charge investigation from the dashboard. The header must read `meta · muse-spark-1.3`, not
   `MOCK · scripted`.

4. Validate the real benchmark without spending tokens:

   ```powershell
   backend\.venv\Scripts\python benchmarks\run_benchmark.py --config benchmarks\configs\muse-spark-1.3.json --dry-run
   ```

   This checks the key (the run refuses the mock fallback, exit code 3), the sandbox and connectivity,
   and prints the worst-case cost (about $24 for 5 defects × 2 systems × 3 repeats; the config caps
   it at $25).

5. Run it:

   ```powershell
   backend\.venv\Scripts\python benchmarks\run_benchmark.py --config benchmarks\configs\muse-spark-1.3.json --yes
   ```

   Results land in `benchmarks/results/<run_id>-meta.{json,html}` and on the dashboard's
   **Evaluation** page. Report per-defect success counts across the three repeats, together with
   failed model calls and token usage. Update `docs/EVALUATION.md` and
   `docs/HACKATHON_SUBMISSION.md` with the real numbers, keeping the mock section labelled as such.

If structured output is rejected, the provider downgrades automatically
(`json_schema → json_object → none`). If outputs are truncated, raise `AI_MAX_TOKENS` or lower
`META_REASONING_EFFORT` (both are in the config file).

## Open decisions for the owner

* Lowering the WSL memory cap in `%USERPROFILE%\.wslconfig` (global setting, not changed).
* Whether to keep `muse-spark-1.3` (standard) or use the `-contributor` variant. It is cheaper, but
  Meta may train on the prompts, which contain repository code.

## Resuming work

```powershell
.\scripts\lite.ps1 start      # dashboard + API on http://127.0.0.1:8010
.\scripts\lite.ps1 stop       # stop everything again
```

See [OPERATIONS.md](OPERATIONS.md) for details and troubleshooting.
