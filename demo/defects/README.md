# Defect catalog (evaluation material — never shown to investigation agents)

FORGE-0 investigates `demo/order-management/`. This directory sits **outside** that repository, so
the reference fixes and descriptions here are never part of the snapshot agents read. Hidden
evaluation tests live in `benchmarks/hidden-tests/`.

| Id | Category | Failing test | Root cause | Reference fix |
| --- | --- | --- | --- | --- |
| [D1-lost-update](D1-lost-update/defect.json) | concurrency | `keeps every item when items are added concurrently` | unguarded read-modify-write in `OrderService.addItem` | per-order lock around read-modify-write cycles |
| [D2-duplicate-charge](D2-duplicate-charge/defect.json) | retries / idempotency | `charges the customer exactly once when a timed-out request is retried` | idempotency key generated inside the retried closure | generate the key once per capture |
| [D3-transaction-leak](D3-transaction-leak/defect.json) | DB transactions | `leaves inventory untouched when a multi-item order fails` | `reserve(this.db, …)` bypasses the transaction | `reserve(tx, …)` |
| [D4-unhandled-async-error](D4-unhandled-async-error/defect.json) | async errors | `reports carrier failures and does not mark the order as shipped` | `forEach(async …)` discards promises | await each shipment inside `try` |
| [D5-terminal-status](D5-terminal-status/defect.json) | validation | `does not allow a cancelled order to be paid or shipped` | empty transition list treated as unrestricted | only listed transitions are allowed |

Each `defect.json` contains the description, relevant files, reproduction steps, failing test,
expected behaviour and regression tests. Each `reference-fix.json` contains search/replace edits in
the same format FORGE-0 uses.

Reproduce all five failures:

```bash
cd demo/order-management
node --test "test/**/*.test.ts"     # 14 pass, 5 fail
```

The integration suite applies every reference fix in the sandbox and checks that its target and
regression tests pass while exactly the other four defects still fail
(`backend/tests/test_integration_docker.py::test_reference_fix_repairs_its_defect_without_regressions`).
