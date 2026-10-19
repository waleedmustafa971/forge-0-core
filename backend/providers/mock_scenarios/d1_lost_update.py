"""Scripted scenario: concurrent addItem calls lose line items."""

E1_SEQUENTIAL = """import assert from 'node:assert/strict';
import { it } from 'node:test';
import { seededApp } from '../helpers.ts';

it('sequential addItem calls keep every item', async () => {
  const app = await seededApp();
  const order = await app.orderService.placeOrder({
    customerId: 'exp',
    items: [{ sku: 'SKU-KEYBOARD', quantity: 1 }],
  });
  await app.orderService.addItem(order.id, { sku: 'SKU-MOUSE', quantity: 1 });
  await app.orderService.addItem(order.id, { sku: 'SKU-CABLE', quantity: 2 });
  const stored = await app.orderService.getOrder(order.id);
  assert.equal(stored.items.length, 3);
});
"""

E2_ISOLATION = """import assert from 'node:assert/strict';
import { it } from 'node:test';
import { InMemoryDatabase } from '../../src/db/database.ts';

it('rows returned by the database are isolated copies', async () => {
  const db = new InMemoryDatabase();
  const row = { id: 'o1', items: ['a'] };
  await db.put('orders', 'o1', row);
  row.items.push('mutated-after-put');
  const first = await db.get<{ id: string; items: string[] }>('orders', 'o1');
  first!.items.push('mutated-after-get');
  const second = await db.get<{ id: string; items: string[] }>('orders', 'o1');
  assert.deepEqual(second!.items, ['a']);
});
"""

SCENARIO = {
    "id": "D1-lost-update",
    "match": "keeps every item when items are added concurrently",
    "hypotheses": {
        "reasoning_summary": (
            "Only the concurrent variant fails; the sequential and single-item tests pass. The stored order "
            "is missing exactly one of the two concurrently added SKUs, which points at a lost update rather "
            "than a computation error. Storage-level aliasing and an item-list logic error are kept as "
            "competing explanations until an experiment separates them."
        ),
        "hypotheses": [
            {
                "key": "H1",
                "title": "Unsynchronized read-modify-write in OrderService.addItem",
                "explanation": (
                    "addItem reads the order, awaits the pricing client, then writes the whole document back. "
                    "Two concurrent calls read the same version and the later write overwrites the earlier one."
                ),
                "suspected_locations": [
                    "src/services/orderService.ts",
                    "src/repositories/orderRepository.ts",
                ],
                "supporting_evidence": [
                    "Failure only appears in the Promise.all test",
                    "Assertion shows one of the two new SKUs missing, not a wrong total",
                ],
                "contradicting_evidence": [],
                "prior": 0.5,
            },
            {
                "key": "H2",
                "title": "InMemoryDatabase leaks shared object references between callers",
                "explanation": (
                    "If get/put returned or stored the caller's object instead of a copy, concurrent callers "
                    "would mutate shared state and one push could be lost when the arrays diverge."
                ),
                "suspected_locations": ["src/db/database.ts"],
                "supporting_evidence": ["Both calls operate on the same order id"],
                "contradicting_evidence": ["database.ts appears to call structuredClone on reads and writes"],
                "prior": 0.25,
            },
            {
                "key": "H3",
                "title": "addItem mishandles orders that already contain several items",
                "explanation": (
                    "A logic error in how the item list is rebuilt would drop an item whenever more than one "
                    "item is added, independent of timing."
                ),
                "suspected_locations": ["src/services/orderService.ts"],
                "supporting_evidence": ["The failing test adds two items"],
                "contradicting_evidence": ["'applies sequential additions in order' passes at baseline"],
                "prior": 0.15,
            },
        ],
    },
    "experiment_rounds": [
        {
            "rationale": (
                "E1 removes concurrency while keeping the same additions (separates H3 from H1/H2). E2 probes "
                "storage isolation directly (separates H2). E3 is a counterfactual intervention: serialize "
                "addItem in a disposable copy and check whether the original failure disappears (H1 predicts it "
                "does, H2/H3 predict it does not)."
            ),
            "experiments": [
                {
                    "key": "E1",
                    "objective": "Do two awaited (non-overlapping) additions both persist?",
                    "kind": "discrimination",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [
                        {"path": "test/forge-experiments/E1-sequential.test.ts", "content": E1_SEQUENTIAL}
                    ],
                    "source_edits": [],
                    "run": ["test/forge-experiments/E1-sequential.test.ts"],
                    "test_name_pattern": None,
                    "predictions": [
                        {"hypothesis": "H1", "outcome": "pass", "rationale": "No overlap, so no lost update"},
                        {"hypothesis": "H2", "outcome": "pass", "rationale": "Aliasing needs interleaving"},
                        {
                            "hypothesis": "H3",
                            "outcome": "fail",
                            "rationale": "Logic error is timing-independent",
                        },
                    ],
                    "success_condition": "All three items are stored after sequential additions",
                    "failure_condition": "Fewer than three items are stored",
                },
                {
                    "key": "E2",
                    "objective": "Does the database isolate stored rows from caller mutations?",
                    "kind": "discrimination",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [
                        {"path": "test/forge-experiments/E2-isolation.test.ts", "content": E2_ISOLATION}
                    ],
                    "source_edits": [],
                    "run": ["test/forge-experiments/E2-isolation.test.ts"],
                    "test_name_pattern": None,
                    "predictions": [
                        {"hypothesis": "H1", "outcome": "pass", "rationale": "Storage is not implicated"},
                        {
                            "hypothesis": "H2",
                            "outcome": "fail",
                            "rationale": "Mutations would leak into storage",
                        },
                        {"hypothesis": "H3", "outcome": "pass", "rationale": "Storage is not implicated"},
                    ],
                    "success_condition": "Stored row is unaffected by mutations of returned/inserted objects",
                    "failure_condition": "Mutations leak into the stored row",
                },
                {
                    "key": "E3",
                    "objective": "Counterfactual: if addItem calls are serialized, does the original failure vanish?",
                    "kind": "intervention",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [],
                    "source_edits": [
                        {
                            "file": "src/services/orderService.ts",
                            "search": "export class OrderService {",
                            "replace": "let experimentQueue: Promise<void> = Promise.resolve();\n\n"
                            "export class OrderService {",
                        },
                        {
                            "file": "src/services/orderService.ts",
                            "search": "  async addItem(orderId: string, item: NewOrderItem): Promise<Order> {\n"
                            "    validateItems([item]);",
                            "replace": "  async addItem(orderId: string, item: NewOrderItem): Promise<Order> {\n"
                            "    const previous = experimentQueue;\n"
                            "    let release!: () => void;\n"
                            "    experimentQueue = new Promise<void>((resolve) => (release = resolve));\n"
                            "    await previous;\n"
                            "    try {\n"
                            "      return await this.addItemUnserialized(orderId, item);\n"
                            "    } finally {\n"
                            "      release();\n"
                            "    }\n"
                            "  }\n\n"
                            "  private async addItemUnserialized(orderId: string, item: NewOrderItem): "
                            "Promise<Order> {\n"
                            "    validateItems([item]);",
                        },
                    ],
                    "run": ["test/orders.test.ts"],
                    "test_name_pattern": "added concurrently",
                    "predictions": [
                        {
                            "hypothesis": "H1",
                            "outcome": "pass",
                            "rationale": "Serialization removes the race",
                        },
                        {
                            "hypothesis": "H2",
                            "outcome": "fail",
                            "rationale": "Aliasing persists when serialized",
                        },
                        {"hypothesis": "H3", "outcome": "fail", "rationale": "Logic error persists"},
                    ],
                    "success_condition": "The original failing test passes once additions are serialized",
                    "failure_condition": "The original test still fails",
                },
            ],
            "conclude": False,
        }
    ],
    "repairs": [
        {
            "hypothesis": "H1",
            "summary": "Serialize read-modify-write cycles per order with a keyed mutex",
            "rationale": (
                "E3 showed the failure disappears when additions are serialized, while E1 and E2 ruled out a "
                "timing-independent logic error and storage aliasing. A per-order mutex keeps updates to "
                "different orders concurrent and also protects transition(), which has the same pattern."
            ),
            "edits": [
                {
                    "file": "src/lib/keyedMutex.ts",
                    "search": "",
                    "replace": (
                        "/** Serializes async critical sections that share the same key. */\n"
                        "export class KeyedMutex {\n"
                        "  private readonly tails = new Map<string, Promise<void>>();\n\n"
                        "  async runExclusive<T>(key: string, work: () => Promise<T>): Promise<T> {\n"
                        "    const previous = this.tails.get(key) ?? Promise.resolve();\n"
                        "    let release!: () => void;\n"
                        "    const current = new Promise<void>((resolve) => {\n"
                        "      release = resolve;\n"
                        "    });\n"
                        "    const tail = previous.then(() => current);\n"
                        "    this.tails.set(key, tail);\n"
                        "    await previous;\n"
                        "    try {\n"
                        "      return await work();\n"
                        "    } finally {\n"
                        "      release();\n"
                        "      if (this.tails.get(key) === tail) this.tails.delete(key);\n"
                        "    }\n"
                        "  }\n"
                        "}\n"
                    ),
                },
                {
                    "file": "src/services/orderService.ts",
                    "search": "import type { OrderRepository } from '../repositories/orderRepository.ts';",
                    "replace": "import type { OrderRepository } from '../repositories/orderRepository.ts';\n"
                    "import { KeyedMutex } from '../lib/keyedMutex.ts';",
                },
                {
                    "file": "src/services/orderService.ts",
                    "search": "  private readonly pricing: PricingClient;\n\n  constructor(",
                    "replace": "  private readonly pricing: PricingClient;\n"
                    "  private readonly orderLocks = new KeyedMutex();\n\n  constructor(",
                },
                {
                    "file": "src/services/orderService.ts",
                    "search": (
                        "    validateItems([item]);\n"
                        "    const order = await this.orders.get(this.db, orderId);\n"
                        "    if (order.status !== 'pending') {\n"
                        "      throw new ValidationError(`Order ${orderId} can no longer be modified`);\n"
                        "    }\n"
                        "    const unitPrice = await this.pricing.priceFor(item.sku);\n"
                        "    order.items.push({ ...item, unitPrice });\n"
                        "    order.total = computeTotal(order.items);\n"
                        "    order.version += 1;\n"
                        "    await this.orders.update(this.db, order);\n"
                        "    return order;\n"
                        "  }"
                    ),
                    "replace": (
                        "    validateItems([item]);\n"
                        "    return this.orderLocks.runExclusive(orderId, async () => {\n"
                        "      const order = await this.orders.get(this.db, orderId);\n"
                        "      if (order.status !== 'pending') {\n"
                        "        throw new ValidationError(`Order ${orderId} can no longer be modified`);\n"
                        "      }\n"
                        "      const unitPrice = await this.pricing.priceFor(item.sku);\n"
                        "      order.items.push({ ...item, unitPrice });\n"
                        "      order.total = computeTotal(order.items);\n"
                        "      order.version += 1;\n"
                        "      await this.orders.update(this.db, order);\n"
                        "      return order;\n"
                        "    });\n"
                        "  }"
                    ),
                },
                {
                    "file": "src/services/orderService.ts",
                    "search": (
                        "    const order = await this.orders.get(this.db, orderId);\n"
                        "    assertTransition(order.status, next);\n"
                        "    order.status = next;\n"
                        "    order.version += 1;\n"
                        "    await this.orders.update(this.db, order);\n"
                        "    return order;"
                    ),
                    "replace": (
                        "    return this.orderLocks.runExclusive(orderId, async () => {\n"
                        "      const order = await this.orders.get(this.db, orderId);\n"
                        "      assertTransition(order.status, next);\n"
                        "      order.status = next;\n"
                        "      order.version += 1;\n"
                        "      await this.orders.update(this.db, order);\n"
                        "      return order;\n"
                        "    });"
                    ),
                },
            ],
            "risk_notes": [
                "The mutex is in-process; multiple service instances would need optimistic versioning instead.",
            ],
        }
    ],
    "one_shot_repair": {
        "hypothesis": "direct",
        "summary": "Run addItem inside a database transaction",
        "rationale": "Concurrent writes overwrite each other; performing the read and write in one transaction "
        "should make the update atomic.",
        "edits": [
            {
                "file": "src/services/orderService.ts",
                "search": (
                    "    validateItems([item]);\n"
                    "    const order = await this.orders.get(this.db, orderId);\n"
                    "    if (order.status !== 'pending') {\n"
                    "      throw new ValidationError(`Order ${orderId} can no longer be modified`);\n"
                    "    }\n"
                    "    const unitPrice = await this.pricing.priceFor(item.sku);\n"
                    "    order.items.push({ ...item, unitPrice });\n"
                    "    order.total = computeTotal(order.items);\n"
                    "    order.version += 1;\n"
                    "    await this.orders.update(this.db, order);\n"
                    "    return order;\n"
                    "  }"
                ),
                "replace": (
                    "    validateItems([item]);\n"
                    "    return this.db.transaction(async (tx) => {\n"
                    "      const order = await this.orders.get(tx, orderId);\n"
                    "      if (order.status !== 'pending') {\n"
                    "        throw new ValidationError(`Order ${orderId} can no longer be modified`);\n"
                    "      }\n"
                    "      const unitPrice = await this.pricing.priceFor(item.sku);\n"
                    "      order.items.push({ ...item, unitPrice });\n"
                    "      order.total = computeTotal(order.items);\n"
                    "      order.version += 1;\n"
                    "      await this.orders.update(tx, order);\n"
                    "      return order;\n"
                    "    });\n"
                    "  }"
                ),
            }
        ],
        "risk_notes": [],
    },
}
