import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { ValidationError } from '../src/domain/types.ts';
import { seededApp } from './helpers.ts';

describe('order line items', () => {
  it('adds a single item and recomputes the total', async () => {
    const app = await seededApp();
    const order = await app.orderService.placeOrder({
      customerId: 'cust-1',
      items: [{ sku: 'SKU-KEYBOARD', quantity: 1 }],
    });
    const updated = await app.orderService.addItem(order.id, { sku: 'SKU-MOUSE', quantity: 2 });
    assert.equal(updated.items.length, 2);
    assert.equal(updated.total, 89.48);
    const stored = await app.orderService.getOrder(order.id);
    assert.deepEqual(
      stored.items.map((i) => i.sku),
      ['SKU-KEYBOARD', 'SKU-MOUSE'],
    );
  });

  it('applies sequential additions in order', async () => {
    const app = await seededApp();
    const order = await app.orderService.placeOrder({
      customerId: 'cust-1',
      items: [{ sku: 'SKU-KEYBOARD', quantity: 1 }],
    });
    await app.orderService.addItem(order.id, { sku: 'SKU-MOUSE', quantity: 1 });
    await app.orderService.addItem(order.id, { sku: 'SKU-CABLE', quantity: 3 });
    const stored = await app.orderService.getOrder(order.id);
    assert.equal(stored.items.length, 3);
    assert.equal(stored.version, 3);
  });

  it('rejects items with invalid quantities', async () => {
    const app = await seededApp();
    const order = await app.orderService.placeOrder({
      customerId: 'cust-1',
      items: [{ sku: 'SKU-KEYBOARD', quantity: 1 }],
    });
    await assert.rejects(
      app.orderService.addItem(order.id, { sku: 'SKU-MOUSE', quantity: 0 }),
      ValidationError,
    );
  });

  it('keeps every item when items are added concurrently', async () => {
    const app = await seededApp();
    const order = await app.orderService.placeOrder({
      customerId: 'cust-1',
      items: [{ sku: 'SKU-KEYBOARD', quantity: 1 }],
    });
    await Promise.all([
      app.orderService.addItem(order.id, { sku: 'SKU-MOUSE', quantity: 1 }),
      app.orderService.addItem(order.id, { sku: 'SKU-CABLE', quantity: 2 }),
    ]);
    const stored = await app.orderService.getOrder(order.id);
    assert.deepEqual(
      stored.items.map((i) => i.sku).sort(),
      ['SKU-CABLE', 'SKU-KEYBOARD', 'SKU-MOUSE'],
    );
    assert.equal(stored.total, 49.5 + 19.99 + 2 * 7.25);
  });
});
