"""Scripted scenario: terminal order statuses accept any transition."""

E1_PURE = """import assert from 'node:assert/strict';
import { it } from 'node:test';
import { canTransition } from '../../src/domain/status.ts';

it('terminal statuses reject outgoing transitions', () => {
  assert.equal(canTransition('cancelled', 'paid'), false);
  assert.equal(canTransition('refunded', 'shipped'), false);
});
"""

E2_PERSIST = """import assert from 'node:assert/strict';
import { it } from 'node:test';
import { seededApp } from '../helpers.ts';

it('cancel() persists the cancelled status', async () => {
  const app = await seededApp();
  const order = await app.orderService.placeOrder({
    customerId: 'exp',
    items: [{ sku: 'SKU-CABLE', quantity: 1 }],
  });
  await app.orderService.cancel(order.id);
  assert.equal((await app.orderService.getOrder(order.id)).status, 'cancelled');
});
"""

E3_SERVICE = """import assert from 'node:assert/strict';
import { it } from 'node:test';
import { InvalidTransitionError } from '../../src/domain/types.ts';
import { seededApp } from '../helpers.ts';

it('transition() enforces the state machine for non-terminal statuses', async () => {
  const app = await seededApp();
  const order = await app.orderService.placeOrder({
    customerId: 'exp',
    items: [{ sku: 'SKU-CABLE', quantity: 1 }],
  });
  await app.orderService.transition(order.id, 'paid');
  await app.orderService.transition(order.id, 'shipped');
  await app.orderService.transition(order.id, 'delivered');
  await assert.rejects(app.orderService.transition(order.id, 'paid'), InvalidTransitionError);
});
"""

SCENARIO = {
    "id": "D5-terminal-status",
    "match": "does not allow a cancelled order to be paid or shipped",
    "hypotheses": {
        "reasoning_summary": (
            "A cancelled order accepted a transition to 'paid'. The rule could be wrong in the pure state machine, "
            "the service could skip validation, or the cancellation may never have been persisted."
        ),
        "hypotheses": [
            {
                "key": "H1",
                "title": "canTransition treats an empty transition list as unrestricted",
                "explanation": (
                    "`allowed.length === 0 || allowed.includes(to)` returns true for every target when the "
                    "source status is terminal (cancelled, refunded)."
                ),
                "suspected_locations": ["src/domain/status.ts:20"],
                "supporting_evidence": ["Only the terminal-status test fails; other transition tests pass"],
                "contradicting_evidence": [],
                "prior": 0.5,
            },
            {
                "key": "H2",
                "title": "OrderService.transition does not consult the state machine",
                "explanation": "If validation were skipped, any transition would succeed.",
                "suspected_locations": ["src/services/orderService.ts"],
                "supporting_evidence": ["The invalid transition succeeded"],
                "contradicting_evidence": ["'rejects moving a shipped order back to pending' passes"],
                "prior": 0.2,
            },
            {
                "key": "H3",
                "title": "cancel() does not persist the cancelled status",
                "explanation": "If the order were still pending, pending -> paid would legitimately be allowed.",
                "suspected_locations": ["src/services/orderService.ts"],
                "supporting_evidence": [],
                "contradicting_evidence": [],
                "prior": 0.2,
            },
        ],
    },
    "experiment_rounds": [
        {
            "rationale": (
                "Each hypothesis blames a different layer, so each experiment isolates one layer: the pure rule "
                "(E1), persistence of the cancellation (E2), and service-level enforcement (E3)."
            ),
            "experiments": [
                {
                    "key": "E1",
                    "objective": "Does the pure rule reject transitions out of terminal statuses?",
                    "kind": "discrimination",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [{"path": "test/forge-experiments/E1-rule.test.ts", "content": E1_PURE}],
                    "source_edits": [],
                    "run": ["test/forge-experiments/E1-rule.test.ts"],
                    "test_name_pattern": None,
                    "predictions": [
                        {"hypothesis": "H1", "outcome": "fail"},
                        {"hypothesis": "H2", "outcome": "pass"},
                        {"hypothesis": "H3", "outcome": "pass"},
                    ],
                    "success_condition": "canTransition returns false for terminal sources",
                    "failure_condition": "canTransition returns true",
                },
                {
                    "key": "E2",
                    "objective": "Is the cancelled status persisted?",
                    "kind": "discrimination",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [{"path": "test/forge-experiments/E2-persist.test.ts", "content": E2_PERSIST}],
                    "source_edits": [],
                    "run": ["test/forge-experiments/E2-persist.test.ts"],
                    "test_name_pattern": None,
                    "predictions": [
                        {"hypothesis": "H1", "outcome": "pass"},
                        {"hypothesis": "H2", "outcome": "pass"},
                        {"hypothesis": "H3", "outcome": "fail"},
                    ],
                    "success_condition": "Stored status is 'cancelled'",
                    "failure_condition": "Stored status is not 'cancelled'",
                },
                {
                    "key": "E3",
                    "objective": "Does transition() reject an invalid move between non-terminal statuses?",
                    "kind": "discrimination",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [{"path": "test/forge-experiments/E3-service.test.ts", "content": E3_SERVICE}],
                    "source_edits": [],
                    "run": ["test/forge-experiments/E3-service.test.ts"],
                    "test_name_pattern": None,
                    "predictions": [
                        {"hypothesis": "H1", "outcome": "pass"},
                        {"hypothesis": "H2", "outcome": "fail"},
                        {"hypothesis": "H3", "outcome": "pass"},
                    ],
                    "success_condition": "delivered -> paid is rejected",
                    "failure_condition": "delivered -> paid is accepted",
                },
            ],
            "conclude": False,
        }
    ],
    "repairs": [
        {
            "hypothesis": "H1",
            "summary": "Treat an empty transition list as terminal",
            "rationale": (
                "E1 reproduced the defect in the pure rule while E2 and E3 cleared persistence and service-level "
                "enforcement. Only explicitly listed transitions should be allowed."
            ),
            "edits": [
                {
                    "file": "src/domain/status.ts",
                    "search": "  return allowed.length === 0 || allowed.includes(to);",
                    "replace": "  return allowed.includes(to);",
                }
            ],
            "risk_notes": [],
        }
    ],
    "one_shot_repair": {
        "hypothesis": "direct",
        "summary": "Treat an empty transition list as terminal",
        "rationale": "canTransition allows everything for statuses without outgoing transitions.",
        "edits": [
            {
                "file": "src/domain/status.ts",
                "search": "  return allowed.length === 0 || allowed.includes(to);",
                "replace": "  return allowed.includes(to);",
            }
        ],
        "risk_notes": [],
    },
}
