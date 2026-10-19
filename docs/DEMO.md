# Demo walkthrough

Everything below works in mock mode, without any API key. Model outputs are scripted (and labelled
as such everywhere); every test run, experiment and verification is a real sandbox execution.

## 0. Start the stack

```powershell
.\scripts\lite.ps1 start   # Windows, lightweight: dashboard + API on http://127.0.0.1:8010
.\scripts\dev.ps1          # Windows, full mode with hot reload: dashboard on http://127.0.0.1:5173
```

```bash
./scripts/dev.sh           # Linux / macOS
```

Open the dashboard (<http://127.0.0.1:8010> in lite mode, <http://127.0.0.1:5173> in full mode). The sidebar footer should show **Database · postgresql**,
**Sandbox · docker …** and **API** in green; the top bar shows **MOCK · scripted**.

## 1. Explore the repository (≈20 s)

**Repositories → order-management (demo)**. The profile shows TypeScript, the `node:test` runner
and the `node:24-alpine` sandbox image. Browse `src/services/orderService.ts`.

Click **Run in sandbox**: the suite runs in an offline, read-only container — 14 passed, 5 failed.
Each failure is one planted defect.

## 2. Investigate the concurrency defect (≈45 s)

**Investigate order-management (demo)** → choose
`order line items > keeps every item when items are added concurrently` → symptom *"Customers report
missing line items after editing orders from two tabs"* → **System B · FORGE-0** → **Start**.

Watch the workspace:

1. **A · Investigator** runs the baseline suite and re-runs the target in isolation (E0 — reproduced).
2. **B · Hypotheses** proposes three competing explanations: a read-modify-write race (H1), storage
   aliasing (H2), an item-list logic error (H3).
3. **C/D · Designer + Executor** run three experiments:
   * E1 — sequential additions pass → H3 refuted;
   * E2 — the database isolates rows → H2 refuted;
   * E3 — *counterfactual*: serialize `addItem` in a disposable copy and the original failure
     disappears → H1 confirmed (96%).
4. **E · Repair** writes a per-order keyed mutex; **F · Verifier** re-runs everything on fresh
   copies: target passes 3/3, 0 regressions, 4 unrelated failures unchanged.

Open **Experiment timeline → Evidence** on E3 to see the predictions table, the belief update and the
intervention diff; **Raw output** shows the exact command, image and sandbox limits.

## 3. Watch the verifier reject a patch (≈45 s)

Start another investigation on
`payment capture > charges the customer exactly once when a timed-out request is retried`.

Experiments confirm the idempotency key is regenerated per retry. The first patch derives the key
from the order id — it fixes the target, but **Patch review** shows it **REJECTED**:
`records separate charges for separate capture calls` went from passed to failed. The Repair
Engineer receives the verifier's findings and the second patch (one key per logical capture) is
verified.

## 4. Compare with Baseline A (≈20 s)

Start the concurrency investigation again with **Baseline A · one-shot**. Its patch wraps `addItem`
in a transaction — plausible, but the in-memory transactions don't lock, so the verifier reports the
target test **still failing**. Baseline A would have claimed this fix; FORGE-0 never claims a fix
the verifier hasn't accepted.

## 5. Evidence report and evaluation

**Evidence report** summarises root cause, rejected hypotheses, supporting experiments, the proposed
fix and usage; **Download .md** exports it. **Evaluation** shows Baseline A vs System B across all
five defects, with hidden-test confirmation and a prominent *mock-only* disclaimer.

## Automated check before presenting

```powershell
backend\.venv\Scripts\python scripts\audit_demo.py
```

Runs step 3 through the API and verifies 17 properties (reproduction, rejection of P1 for the
`records separate charges` regression, verification of P2, the complete evidence timeline, Markdown
export, simulated labelling). Last result: 17/17.

## 6. Switch to Muse Spark

See [API_INTEGRATION.md](API_INTEGRATION.md): add `META_API_KEY`, set `AI_PROVIDER=meta`, restart,
run `scripts/check_meta.py`, repeat steps 2–4 with real inference.
