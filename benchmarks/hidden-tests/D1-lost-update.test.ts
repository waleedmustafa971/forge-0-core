// Hidden evaluation test: copied to test/hidden/ in a disposable copy by the benchmark harness.
// Never shown to investigation agents.
import assert from 'node:assert/strict';
import { it } from 'node:test';
import { seededApp } from '../helpers.ts';

it('[hidden] five concurrent additions are all persisted', async () => {
  const app = await seededApp();
  const order = await app.orderService.placeOrder({
    customerId: 'c',
    items: [{ sku: 'SKU-KEYBOARD', quantity: 1 }],
  });
  const skus = ['SKU-MOUSE', 'SKU-CABLE', 'SKU-MONITOR', 'SKU-MOUSE', 'SKU-CABLE'];
  await Promise.all(skus.map((sku) => app.orderService.addItem(order.id, { sku, quantity: 1 })));
  const stored = await app.orderService.getOrder(order.id);
  assert.equal(stored.items.length, 6);
  assert.equal(stored.version, 6);
});

it('[hidden] concurrent updates on different orders do not interfere', async () => {
  const app = await seededApp();
  const a = await app.orderService.placeOrder({ customerId: 'a', items: [{ sku: 'SKU-CABLE', quantity: 1 }] });
  const b = await app.orderService.placeOrder({ customerId: 'b', items: [{ sku: 'SKU-CABLE', quantity: 1 }] });
  await Promise.all([
    app.orderService.addItem(a.id, { sku: 'SKU-MOUSE', quantity: 1 }),
    app.orderService.addItem(b.id, { sku: 'SKU-KEYBOARD', quantity: 1 }),
    app.orderService.addItem(a.id, { sku: 'SKU-KEYBOARD', quantity: 1 }),
  ]);
  assert.equal((await app.orderService.getOrder(a.id)).items.length, 3);
  assert.equal((await app.orderService.getOrder(b.id)).items.length, 2);
});

it('[hidden] a failed addition does not block later additions', async () => {
  const app = await seededApp();
  const order = await app.orderService.placeOrder({ customerId: 'c', items: [{ sku: 'SKU-CABLE', quantity: 1 }] });
  await assert.rejects(app.orderService.addItem(order.id, { sku: 'SKU-UNKNOWN', quantity: 1 }));
  await app.orderService.addItem(order.id, { sku: 'SKU-MOUSE', quantity: 1 });
  assert.equal((await app.orderService.getOrder(order.id)).items.length, 2);
});
