# Contributing to FORGE-0

## Setup

See the README quick start (`scripts/dev.ps1` or `scripts/dev.sh`). Requirements: Python 3.12+,
Node.js 22.18+ (24 recommended), Docker (Desktop, or Engine inside WSL2).

## Checks (the same ones CI runs)

```bash
# backend
cd backend
ruff check . && ruff format --check .
pytest -m "not docker and not postgres"          # unit + API tests, no infrastructure needed
pytest -m "docker or postgres"                   # needs Docker; set TEST_POSTGRES_URL for Postgres

# frontend
cd frontend
npm run lint && npm run typecheck && npm test && npm run build

# demo service
cd demo/order-management
npm ci && npm run typecheck
node --test "test/**/*.test.ts"                  # must report exactly 14 pass / 5 fail
```

## Ground rules

* **Never fabricate results.** Mock output must stay labelled `simulated`; metrics that were not
  measured are `null`, not estimated.
* **Untrusted code runs only in the sandbox.** Don't add host-side execution of repository code or
  model output. New runners must be allowlisted in `backend/sandbox/runners.py` with validated
  arguments.
* **Don't weaken sandbox flags** in `sandbox/docker.py` without a security review; the isolation
  tests in `tests/test_integration_docker.py` must keep passing.
* **No secrets in code, logs, fixtures or commits.** Use `.env` (git-ignored).
* Schema changes need an Alembic migration in `backend/alembic/versions/`.
* Model-facing changes go through the Pydantic contracts in `core/schemas.py`; update the mock
  scenarios and prompts together.
* Keep reference fixes and hidden tests out of `demo/order-management/`.

## Adding a demo defect

1. Introduce the bug and a failing test in `demo/order-management`.
2. Add `demo/defects/<id>/defect.json` and `reference-fix.json`.
3. Add `benchmarks/hidden-tests/<id>.test.ts` (tests named `[hidden] …`).
4. Optionally script a mock scenario in `backend/providers/mock_scenarios/`.
5. Update the expected pass/fail counts in CI and tests.

## Commits

Small, focused commits with imperative subject lines. Pull requests must pass CI.
