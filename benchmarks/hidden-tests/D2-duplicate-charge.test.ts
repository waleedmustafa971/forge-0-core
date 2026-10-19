// Hidden evaluation test: copied to test/hidden/ in a disposable copy by the benchmark harness.
import assert from 'node:assert/strict';
import { it } from 'node:test';
import { seededApp } from '../helpers.ts';

it('[hidden] repeated timeouts still produce a single charge', async () => {
  const app = await seededApp();
  app.paymentGateway.failNextResponses(2);
  await app.paymentService.capturePayment('order-9', 10);
  assert.equal(app.paymentGateway.requests.length, 3);
  assert.equal(app.paymentGateway.charges.length, 1);
  const keys = new Set(app.paymentGateway.requests.map((r) => r.idempotencyKey));
  assert.equal(keys.size, 1, 'all retries of one capture share an idempotency key');
});

it('[hidden] separate captures use distinct idempotency keys', async () => {
  const app = await seededApp();
  await app.paymentService.capturePayment('order-9', 10);
  await app.paymentService.capturePayment('order-9', 10);
  const keys = new Set(app.paymentGateway.requests.map((r) => r.idempotencyKey));
  assert.equal(keys.size, 2);
  assert.equal(app.paymentGateway.charges.length, 2);
});
