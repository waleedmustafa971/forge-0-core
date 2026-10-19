import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { canTransition } from '../src/domain/status.ts';
import { InvalidTransitionError } from '../src/domain/types.ts';
import { seededApp } from './helpers.ts';

describe('order status lifecycle', () => {
  it('allows the standard happy path', async () => {
    const app = await seededApp();
    const order = await app.orderService.placeOrder({
      customerId: 'cust-1',
      items: [{ sku: 'SKU-CABLE', quantity: 1 }],
    });
    await app.orderService.transition(order.id, 'paid');
    await app.orderService.transition(order.id, 'shipped');
    const delivered = await app.orderService.transition(order.id, 'delivered');
    assert.equal(delivered.status, 'delivered');
  });

  it('rejects moving a shipped order back to pending', async () => {
    const app = await seededApp();
    const order = await app.orderService.placeOrder({
      customerId: 'cust-1',
      items: [{ sku: 'SKU-CABLE', quantity: 1 }],
    });
    await app.orderService.transition(order.id, 'paid');
    await app.orderService.transition(order.id, 'shipped');
    await assert.rejects(app.orderService.transition(order.id, 'pending'), InvalidTransitionError);
  });

  it('treats re-applying the current status as a no-op', () => {
    assert.equal(canTransition('paid', 'paid'), true);
  });

  it('does not allow a cancelled order to be paid or shipped', async () => {
    const app = await seededApp();
    const order = await app.orderService.placeOrder({
      customerId: 'cust-1',
      items: [{ sku: 'SKU-CABLE', quantity: 1 }],
    });
    await app.orderService.cancel(order.id);
    await assert.rejects(app.orderService.transition(order.id, 'paid'), InvalidTransitionError);
    await assert.rejects(app.orderService.transition(order.id, 'shipped'), InvalidTransitionError);
    assert.equal((await app.orderService.getOrder(order.id)).status, 'cancelled');
  });
});
