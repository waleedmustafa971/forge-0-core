"""Scripted scenario: retried payment capture charges twice."""

E1_RETRY = """import assert from 'node:assert/strict';
import { it } from 'node:test';
import { withRetry } from '../../src/lib/retry.ts';

it('withRetry invokes a succeeding operation exactly once', async () => {
  let calls = 0;
  const value = await withRetry(async () => {
    calls++;
    return 'ok';
  }, { retries: 3 });
  assert.equal(value, 'ok');
  assert.equal(calls, 1);
});

it('withRetry stops after the first successful retry', async () => {
  let calls = 0;
  await withRetry(async () => {
    calls++;
    if (calls === 1) throw new Error('transient');
    return 'ok';
  }, { retries: 3, baseDelayMs: 0 });
  assert.equal(calls, 2);
});
"""

E2_GATEWAY = """import assert from 'node:assert/strict';
import { it } from 'node:test';
import { FakePaymentGateway } from '../../src/gateways/paymentGateway.ts';

it('gateway de-duplicates replays that share an idempotency key', async () => {
  const gateway = new FakePaymentGateway();
  await gateway.charge({ orderId: 'o1', amount: 10, idempotencyKey: 'k1' });
  await gateway.charge({ orderId: 'o1', amount: 10, idempotencyKey: 'k1' });
  assert.equal(gateway.charges.length, 1);
});
"""

E3_KEYS = """import assert from 'node:assert/strict';
import { it } from 'node:test';
import { seededApp } from '../helpers.ts';

it('retries of one capture reuse the same idempotency key', async () => {
  const app = await seededApp();
  app.paymentGateway.failNextResponses(1);
  await app.paymentService.capturePayment('order-x', 25);
  const keys = app.paymentGateway.requests.map((r) => r.idempotencyKey);
  assert.equal(keys.length, 2);
  assert.equal(keys[0], keys[1], 'idempotency key changed between attempts');
});
"""

SCENARIO = {
    "id": "D2-duplicate-charge",
    "match": "charges the customer exactly once when a timed-out request is retried",
    "hypotheses": {
        "reasoning_summary": (
            "The gateway recorded two charges for one capture after a single lost response. Either the retry "
            "is not recognisable as a replay (idempotency key), the retry helper runs the operation too often, "
            "or the fake gateway's replay protection is broken."
        ),
        "hypotheses": [
            {
                "key": "H1",
                "title": "A new idempotency key is generated on every retry attempt",
                "explanation": (
                    "capturePayment creates the key inside the closure passed to withRetry, so the retried "
                    "request carries a different key and the gateway cannot de-duplicate it."
                ),
                "suspected_locations": ["src/services/paymentService.ts"],
                "supporting_evidence": ["randomUUID() is called inside the retried operation"],
                "contradicting_evidence": [],
                "prior": 0.5,
            },
            {
                "key": "H2",
                "title": "withRetry re-invokes the operation after it has already succeeded",
                "explanation": "An off-by-one or missing return in the retry loop would issue an extra request.",
                "suspected_locations": ["src/lib/retry.ts"],
                "supporting_evidence": ["Two requests were observed"],
                "contradicting_evidence": [
                    "'captures a payment once when the gateway responds normally' passes"
                ],
                "prior": 0.25,
            },
            {
                "key": "H3",
                "title": "FakePaymentGateway does not honour idempotency keys",
                "explanation": "If replays with the same key created new charges, any retry would double-charge.",
                "suspected_locations": ["src/gateways/paymentGateway.ts"],
                "supporting_evidence": ["charges.length is 2"],
                "contradicting_evidence": [],
                "prior": 0.2,
            },
        ],
    },
    "experiment_rounds": [
        {
            "rationale": (
                "Test each component in isolation: E1 the retry helper (H2), E2 the gateway's replay protection "
                "(H3), and E3 whether the key actually changes between attempts (H1)."
            ),
            "experiments": [
                {
                    "key": "E1",
                    "objective": "Does withRetry call a succeeding operation exactly once?",
                    "kind": "discrimination",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [{"path": "test/forge-experiments/E1-retry.test.ts", "content": E1_RETRY}],
                    "source_edits": [],
                    "run": ["test/forge-experiments/E1-retry.test.ts"],
                    "test_name_pattern": None,
                    "predictions": [
                        {"hypothesis": "H1", "outcome": "pass"},
                        {
                            "hypothesis": "H2",
                            "outcome": "fail",
                            "rationale": "Extra invocation after success",
                        },
                        {"hypothesis": "H3", "outcome": "pass"},
                    ],
                    "success_condition": "Operation called once on success, twice after one transient failure",
                    "failure_condition": "Operation called more often than necessary",
                },
                {
                    "key": "E2",
                    "objective": "Does the gateway de-duplicate requests that share an idempotency key?",
                    "kind": "discrimination",
                    "hypotheses": ["H1", "H2", "H3"],
                    "files": [{"path": "test/forge-experiments/E2-gateway.test.ts", "content": E2_GATEWAY}],
                    "source_edits": [],
                    "run": ["test/forge-experiments/E2-gateway.test.ts"],
                    "test_name_pattern": None,
                    "predictions": [
                        {"hypothesis": "H1", "outcome": "pass"},
                        {"hypothesis": "H2", "outcome": "pass"},
                        {
                            "hypothesis": "H3",
                            "outcome": "fail",
                            "rationale": "Replay creates a second charge",
                        },
                    ],
                    "success_condition": "One charge for two requests with the same key",
                    "failure_condition": "Two charges recorded",
                },
                {
                    "key": "E3",
                    "objective": "Do the original request and its retry carry the same idempotency key?",
                    "kind": "discrimination",
                    "hypotheses": ["H1", "H3"],
                    "files": [{"path": "test/forge-experiments/E3-keys.test.ts", "content": E3_KEYS}],
                    "source_edits": [],
                    "run": ["test/forge-experiments/E3-keys.test.ts"],
                    "test_name_pattern": None,
                    "predictions": [
                        {
                            "hypothesis": "H1",
                            "outcome": "fail",
                            "output_contains": "idempotency key changed between attempts",
                        },
                        {
                            "hypothesis": "H3",
                            "outcome": "pass",
                            "rationale": "Keys are fine; gateway is at fault",
                        },
                    ],
                    "success_condition": "Both requests share one key",
                    "failure_condition": "The retry carries a different key",
                },
            ],
            "conclude": False,
        }
    ],
    "repairs": [
        {
            "hypothesis": "H1",
            "summary": "Derive the idempotency key from the order id",
            "rationale": (
                "E3 confirmed the key changes between attempts. Deriving it deterministically from the order "
                "makes every retry of a capture reuse the same key."
            ),
            "edits": [
                {
                    "file": "src/services/paymentService.ts",
                    "search": "        const idempotencyKey = randomUUID();",
                    "replace": "        const idempotencyKey = `capture:${orderId}`;",
                }
            ],
            "risk_notes": ["Assumes one capture per order"],
        },
        {
            "hypothesis": "H1",
            "summary": "Generate the idempotency key once per capture, outside the retry loop",
            "rationale": (
                "Verification of the previous attempt showed a regression: separate captures for the same order "
                "were collapsed into one charge. The key must identify one logical capture, not the order, so it "
                "is generated once before withRetry and reused by every attempt."
            ),
            "edits": [
                {
                    "file": "src/services/paymentService.ts",
                    "search": (
                        "    const result = await withRetry(\n"
                        "      async () => {\n"
                        "        const idempotencyKey = randomUUID();\n"
                        "        return this.gateway.charge({ orderId, amount, idempotencyKey });\n"
                        "      },"
                    ),
                    "replace": (
                        "    // One key per logical capture: every retry of this call must be a replay.\n"
                        "    const idempotencyKey = randomUUID();\n"
                        "    const result = await withRetry(\n"
                        "      async () => this.gateway.charge({ orderId, amount, idempotencyKey }),"
                    ),
                }
            ],
            "risk_notes": [],
        },
    ],
    "one_shot_repair": {
        "hypothesis": "direct",
        "summary": "Derive the idempotency key from the order id",
        "rationale": "Retries generate new keys, so derive a stable key from the order.",
        "edits": [
            {
                "file": "src/services/paymentService.ts",
                "search": "        const idempotencyKey = randomUUID();",
                "replace": "        const idempotencyKey = `capture:${orderId}`;",
            }
        ],
        "risk_notes": [],
    },
}
