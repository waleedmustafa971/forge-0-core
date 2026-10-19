"""Scripted scenario: shipment failures escape error handling."""

E1_GATEWAY = """import assert from 'node:assert/strict';
import { it } from 'node:test';
import { CarrierUnavailableError, FakeShippingGateway } from '../../src/gateways/shippingGateway.ts';

it('a configured carrier failure rejects createShipment', async () => {
  const gateway = new FakeShippingGateway();
  gateway.failFor('SKU-X');
  await assert.rejects(
    gateway.createShipment('o1', { sku: 'SKU-X', quantity: 1, unitPrice: 1 }),
    CarrierUnavailableError,
  );
});
"""

E2_TIMING = """import assert from 'node:assert/strict';
import { it } from 'node:test';
import { paidOrder, seededApp } from '../helpers.ts';

it('fulfill() resolves only after every shipment is booked', async () => {
  const app = await seededApp();
  const order = await paidOrder(app, ['SKU-KEYBOARD', 'SKU-MOUSE', 'SKU-CABLE']);
  await app.fulfillmentService.fulfill(order.id);
  assert.equal(app.shippingGateway.shipments.length, 3, 'fulfill resolved before shipments completed');
});
"""

FOREACH = (
    "      order.items.forEach(async (item) => {\n"
    "        await this.shipping.createShipment(order.id, item);\n"
    "      });"
)

SCENARIO = {
    "id": "D4-unhandled-async-error",
    "match": "reports carrier failures and does not mark the order as shipped",
    "hypotheses": {
        "reasoning_summary": (
            "fulfill() resolved instead of rejecting with FulfillmentError while one SKU was configured to fail. "
            "Either the shipment promises are never awaited, the fake carrier never actually fails, or the error "
            "is raised only after the status has been persisted."
        ),
        "hypotheses": [
            {
                "key": "H1",
                "title": "forEach(async ...) discards shipment promises, bypassing try/catch",
                "explanation": (
                    "Array.prototype.forEach ignores returned promises, so fulfill() continues immediately, marks "
                    "the order shipped, and carrier errors surface later as unhandled rejections."
                ),
                "suspected_locations": ["src/services/fulfillmentService.ts:23"],
                "supporting_evidence": ["'Missing expected rejection (FulfillmentError)'"],
                "contradicting_evidence": [],
                "prior": 0.55,
            },
            {
                "key": "H2",
                "title": "FakeShippingGateway.failFor does not make createShipment reject",
                "explanation": "If the failure is never injected, fulfillment legitimately succeeds.",
                "suspected_locations": ["src/gateways/shippingGateway.ts"],
                "supporting_evidence": ["No error reached the caller"],
                "contradicting_evidence": [],
                "prior": 0.2,
            },
            {
                "key": "H3",
                "title": "Status is persisted before the shipment error is raised",
                "explanation": "An ordering bug would mark the order shipped even when an error is thrown.",
                "suspected_locations": ["src/services/fulfillmentService.ts"],
                "supporting_evidence": [],
                "contradicting_evidence": ["The test reports a missing rejection, not just a wrong status"],
                "prior": 0.15,
            },
        ],
    },
    "experiment_rounds": [
        {
            "rationale": (
                "E1 checks failure injection in isolation (H2). E2 measures whether fulfill() waits for shipments "
                "on the success path (H1 predicts it does not). E3 is the counterfactual: await each shipment in a "
                "disposable copy and re-run the original test."
            ),
            "experiments": [
                {
                    "key": "E1",
                    "objective": "Does failFor() make createShipment reject?",
                    "kind": "discrimination",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [{"path": "test/forge-experiments/E1-gateway.test.ts", "content": E1_GATEWAY}],
                    "source_edits": [],
                    "run": ["test/forge-experiments/E1-gateway.test.ts"],
                    "test_name_pattern": None,
                    "predictions": [
                        {"hypothesis": "H1", "outcome": "pass"},
                        {"hypothesis": "H2", "outcome": "fail"},
                        {"hypothesis": "H3", "outcome": "pass"},
                    ],
                    "success_condition": "createShipment rejects with CarrierUnavailableError",
                    "failure_condition": "createShipment resolves",
                },
                {
                    "key": "E2",
                    "objective": "Are all shipments booked by the time fulfill() resolves?",
                    "kind": "discrimination",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [{"path": "test/forge-experiments/E2-timing.test.ts", "content": E2_TIMING}],
                    "source_edits": [],
                    "run": ["test/forge-experiments/E2-timing.test.ts"],
                    "test_name_pattern": None,
                    "predictions": [
                        {
                            "hypothesis": "H1",
                            "outcome": "fail",
                            "output_contains": "fulfill resolved before shipments completed",
                        },
                        {"hypothesis": "H2", "outcome": "pass"},
                        {"hypothesis": "H3", "outcome": "pass"},
                    ],
                    "success_condition": "3 shipments exist when fulfill() resolves",
                    "failure_condition": "fulfill() resolves first",
                },
                {
                    "key": "E3",
                    "objective": "Counterfactual: if each shipment is awaited, does the original failure vanish?",
                    "kind": "intervention",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [],
                    "source_edits": [
                        {
                            "file": "src/services/fulfillmentService.ts",
                            "search": FOREACH,
                            "replace": "      for (const item of order.items) {\n"
                            "        await this.shipping.createShipment(order.id, item);\n"
                            "      }",
                        }
                    ],
                    "run": ["test/fulfillment.test.ts"],
                    "test_name_pattern": "carrier failures",
                    "predictions": [
                        {"hypothesis": "H1", "outcome": "pass"},
                        {"hypothesis": "H2", "outcome": "fail"},
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
            "hypothesis": "H1",
            "summary": "Await all shipments with Promise.all inside the try block",
            "rationale": (
                "E2 showed fulfill() resolves before shipments complete and E3 that awaiting them fixes the "
                "original failure. Promise.all keeps shipments concurrent while propagating the first error to the "
                "catch block, so the status update only runs after every shipment succeeds."
            ),
            "edits": [
                {
                    "file": "src/services/fulfillmentService.ts",
                    "search": FOREACH,
                    "replace": "      await Promise.all(order.items.map((item) => "
                    "this.shipping.createShipment(order.id, item)));",
                }
            ],
            "risk_notes": [
                "Other shipments of a failed order may still be booked; compensation is out of scope."
            ],
        }
    ],
    "one_shot_repair": {
        "hypothesis": "direct",
        "summary": "Await all shipments with Promise.all",
        "rationale": "forEach does not await async callbacks; use Promise.all so errors reach the catch block.",
        "edits": [
            {
                "file": "src/services/fulfillmentService.ts",
                "search": FOREACH,
                "replace": "      await Promise.all(order.items.map((item) => "
                "this.shipping.createShipment(order.id, item)));",
            }
        ],
        "risk_notes": [],
    },
}
