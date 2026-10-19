"""Scripted scenario: failed checkout leaks stock reservations."""

E1_ROLLBACK = """import assert from 'node:assert/strict';
import { it } from 'node:test';
import { InMemoryDatabase } from '../../src/db/database.ts';

it('writes made through a transaction are discarded on rollback', async () => {
  const db = new InMemoryDatabase();
  await db.put('inventory', 'SKU-X', { sku: 'SKU-X', available: 5 });
  await assert.rejects(
    db.transaction(async (tx) => {
      await tx.put('inventory', 'SKU-X', { sku: 'SKU-X', available: 1 });
      throw new Error('abort');
    }),
    /abort/,
  );
  const row = await db.get<{ available: number }>('inventory', 'SKU-X');
  assert.equal(row?.available, 5);
});

it('writes made through a transaction are applied on commit', async () => {
  const db = new InMemoryDatabase();
  await db.transaction(async (tx) => {
    await tx.put('inventory', 'SKU-X', { sku: 'SKU-X', available: 1 });
  });
  const row = await db.get<{ available: number }>('inventory', 'SKU-X');
  assert.equal(row?.available, 1);
});
"""

E2_RESERVE = """import assert from 'node:assert/strict';
import { it } from 'node:test';
import { InMemoryDatabase } from '../../src/db/database.ts';
import { InventoryRepository } from '../../src/repositories/inventoryRepository.ts';

it('a rejected reservation leaves stock unchanged', async () => {
  const db = new InMemoryDatabase();
  const inventory = new InventoryRepository();
  await inventory.setStock(db, 'SKU-X', 2);
  await assert.rejects(inventory.reserve(db, 'SKU-X', 3));
  assert.equal(await inventory.available(db, 'SKU-X'), 2);
});
"""

SCENARIO = {
    "id": "D3-transaction-leak",
    "match": "leaves inventory untouched when a multi-item order fails",
    "hypotheses": {
        "reasoning_summary": (
            "Keyboard stock dropped from 5 to 3 even though the order was rejected, so the first item's "
            "reservation survived the failure of the second. Either the transaction does not roll back, the "
            "reservation bypasses the transaction, or a single reservation is not atomic."
        ),
        "hypotheses": [
            {
                "key": "H1",
                "title": "InMemoryDatabase.transaction does not discard writes on rollback",
                "explanation": "If rollback left buffered writes in place, every write in a failed checkout leaks.",
                "suspected_locations": ["src/db/database.ts"],
                "supporting_evidence": ["Partial state persisted after a thrown error inside a transaction"],
                "contradicting_evidence": [
                    "'rejects orders that exceed available stock' leaves no order behind"
                ],
                "prior": 0.3,
            },
            {
                "key": "H2",
                "title": "placeOrder reserves stock through the root handle instead of the transaction",
                "explanation": (
                    "inventory.reserve is called with this.db rather than tx, so each reservation is committed "
                    "immediately and is not covered by the rollback."
                ),
                "suspected_locations": ["src/services/orderService.ts:56"],
                "supporting_evidence": [
                    "The order insert (via tx) is rolled back but the reservation is not"
                ],
                "contradicting_evidence": [],
                "prior": 0.5,
            },
            {
                "key": "H3",
                "title": "InventoryRepository.reserve decrements before validating availability",
                "explanation": "A reservation that fails could still have written the decremented stock.",
                "suspected_locations": ["src/repositories/inventoryRepository.ts"],
                "supporting_evidence": [],
                "contradicting_evidence": [
                    "The leaked stock belongs to the item that succeeded, not the failing one"
                ],
                "prior": 0.15,
            },
        ],
    },
    "experiment_rounds": [
        {
            "rationale": (
                "E1 checks rollback semantics in isolation (H1), E2 checks reservation atomicity (H3), and E3 is a "
                "counterfactual: route the reservation through tx in a disposable copy and re-run the original test "
                "(only H2 predicts the failure disappears)."
            ),
            "experiments": [
                {
                    "key": "E1",
                    "objective": "Are transactional writes discarded on rollback and applied on commit?",
                    "kind": "discrimination",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [{"path": "test/forge-experiments/E1-rollback.test.ts", "content": E1_ROLLBACK}],
                    "source_edits": [],
                    "run": ["test/forge-experiments/E1-rollback.test.ts"],
                    "test_name_pattern": None,
                    "predictions": [
                        {"hypothesis": "H1", "outcome": "fail", "rationale": "Rollback would keep the write"},
                        {"hypothesis": "H2", "outcome": "pass"},
                        {"hypothesis": "H3", "outcome": "pass"},
                    ],
                    "success_condition": "Rollback discards, commit applies",
                    "failure_condition": "Rolled-back write is visible",
                },
                {
                    "key": "E2",
                    "objective": "Does a failed reservation leave stock unchanged?",
                    "kind": "discrimination",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [{"path": "test/forge-experiments/E2-reserve.test.ts", "content": E2_RESERVE}],
                    "source_edits": [],
                    "run": ["test/forge-experiments/E2-reserve.test.ts"],
                    "test_name_pattern": None,
                    "predictions": [
                        {"hypothesis": "H1", "outcome": "pass"},
                        {"hypothesis": "H2", "outcome": "pass"},
                        {
                            "hypothesis": "H3",
                            "outcome": "fail",
                            "rationale": "Decrement happens before the check",
                        },
                    ],
                    "success_condition": "Stock remains 2",
                    "failure_condition": "Stock changed",
                },
                {
                    "key": "E3",
                    "objective": "Counterfactual: if reservations go through tx, does the original failure vanish?",
                    "kind": "intervention",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [],
                    "source_edits": [
                        {
                            "file": "src/services/orderService.ts",
                            "search": "await this.inventory.reserve(this.db, item.sku, item.quantity);",
                            "replace": "await this.inventory.reserve(tx, item.sku, item.quantity);",
                        }
                    ],
                    "run": ["test/checkout.test.ts"],
                    "test_name_pattern": "multi-item order fails",
                    "predictions": [
                        {"hypothesis": "H1", "outcome": "fail", "rationale": "Rollback is still broken"},
                        {
                            "hypothesis": "H2",
                            "outcome": "pass",
                            "rationale": "Reservation is now rolled back",
                        },
                        {"hypothesis": "H3", "outcome": "fail"},
                    ],
                    "success_condition": "Original test passes",
                    "failure_condition": "Original test still fails",
                },
            ],
            "conclude": False,
        }
    ],
    "repairs": [
        {
            "hypothesis": "H2",
            "summary": "Reserve stock through the transaction handle",
            "rationale": (
                "E1 showed rollback works and E2 that reservations are atomic; E3 showed the failure vanishes when "
                "the reservation uses tx. Passing tx makes reservations commit or roll back with the order."
            ),
            "edits": [
                {
                    "file": "src/services/orderService.ts",
                    "search": "await this.inventory.reserve(this.db, item.sku, item.quantity);",
                    "replace": "await this.inventory.reserve(tx, item.sku, item.quantity);",
                }
            ],
            "risk_notes": [],
        }
    ],
    "one_shot_repair": {
        "hypothesis": "direct",
        "summary": "Reserve stock through the transaction handle",
        "rationale": "placeOrder passes this.db to reserve inside a transaction; it should pass tx.",
        "edits": [
            {
                "file": "src/services/orderService.ts",
                "search": "await this.inventory.reserve(this.db, item.sku, item.quantity);",
                "replace": "await this.inventory.reserve(tx, item.sku, item.quantity);",
            }
        ],
        "risk_notes": [],
    },
}
