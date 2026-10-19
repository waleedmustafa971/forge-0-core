import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { InsufficientStockError } from '../src/domain/types.ts';
import { seededApp } from './helpers.ts';

describe('checkout', () => {
  it('reserves stock and persists the order on success', async () => {
    const app = await seededApp({ 'SKU-MONITOR': 3 });
    const order = await app.orderService.placeOrder({
      customerId: 'cust-1',
      items: [
        { sku: 'SKU-MONITOR', quantity: 2 },
        { sku: 'SKU-CABLE', quantity: 4 },
      ],
    });
    assert.equal(order.status, 'pending');
    assert.equal(order.total, 2 * 189 + 4 * 7.25);
    assert.equal(await app.inventory.available(app.db, 'SKU-MONITOR'), 1);
    assert.equal(await app.inventory.available(app.db, 'SKU-CABLE'), 46);
    const stored = await app.orderService.getOrder(order.id);
    assert.equal(stored.items.length, 2);
  });

  it('rejects orders that exceed available stock', async () => {
    const app = await seededApp({ 'SKU-MONITOR': 1 });
    await assert.rejects(
      app.orderService.placeOrder({
        customerId: 'cust-1',
        items: [{ sku: 'SKU-MONITOR', quantity: 2 }],
      }),
      InsufficientStockError,
    );
    assert.deepEqual(await app.orders.list(app.db), []);
  });

  it('leaves inventory untouched when a multi-item order fails', async () => {
    const app = await seededApp({ 'SKU-KEYBOARD': 5, 'SKU-MONITOR': 1 });
    await assert.rejects(
      app.orderService.placeOrder({
        customerId: 'cust-1',
        items: [
          { sku: 'SKU-KEYBOARD', quantity: 2 },
          { sku: 'SKU-MONITOR', quantity: 3 },
        ],
      }),
      InsufficientStockError,
    );
    assert.equal(await app.inventory.available(app.db, 'SKU-KEYBOARD'), 5);
    assert.equal(await app.inventory.available(app.db, 'SKU-MONITOR'), 1);
    assert.deepEqual(await app.orders.list(app.db), []);
  });
});
