import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { CardDeclinedError, GatewayTimeoutError } from '../src/gateways/paymentGateway.ts';
import { seededApp } from './helpers.ts';

describe('payment capture', () => {
  it('captures a payment once when the gateway responds normally', async () => {
    const app = await seededApp();
    const record = await app.paymentService.capturePayment('order-1', 120);
    assert.equal(record.status, 'captured');
    assert.equal(app.paymentGateway.charges.length, 1);
    assert.equal(app.paymentGateway.requests.length, 1);
  });

  it('does not retry declined cards', async () => {
    const app = await seededApp();
    app.paymentGateway.declineNextCharge();
    await assert.rejects(app.paymentService.capturePayment('order-1', 50), CardDeclinedError);
    assert.equal(app.paymentGateway.requests.length, 1);
    assert.equal(app.paymentGateway.charges.length, 0);
  });

  it('gives up after exhausting retries on persistent timeouts', async () => {
    const app = await seededApp();
    app.paymentGateway.failNextResponses(10);
    await assert.rejects(app.paymentService.capturePayment('order-1', 50), GatewayTimeoutError);
    assert.equal(app.paymentGateway.requests.length, 4);
  });

  it('records separate charges for separate capture calls', async () => {
    const app = await seededApp();
    await app.paymentService.capturePayment('order-1', 30);
    await app.paymentService.capturePayment('order-1', 70);
    assert.equal(app.paymentGateway.charges.length, 2);
  });

  it('charges the customer exactly once when a timed-out request is retried', async () => {
    const app = await seededApp();
    app.paymentGateway.failNextResponses(1);
    const record = await app.paymentService.capturePayment('order-7', 99);
    assert.equal(record.amount, 99);
    assert.equal(app.paymentGateway.requests.length, 2, 'the timed-out request should be retried');
    assert.equal(app.paymentGateway.charges.length, 1, 'customer must be charged exactly once');
  });
});
