// Hidden evaluation test: copied to test/hidden/ in a disposable copy by the benchmark harness.
import assert from 'node:assert/strict';
import { it } from 'node:test';
import { seededApp } from '../helpers.ts';

it('[hidden] failure on the last of three items rolls back all reservations', async () => {
  const app = await seededApp({ 'SKU-KEYBOARD': 4, 'SKU-MOUSE': 4, 'SKU-MONITOR': 0 });
  await assert.rejects(
    app.orderService.placeOrder({
      customerId: 'c',
      items: [
        { sku: 'SKU-KEYBOARD', quantity: 1 },
        { sku: 'SKU-MOUSE', quantity: 2 },
        { sku: 'SKU-MONITOR', quantity: 1 },
      ],
    }),
  );
  assert.equal(await app.inventory.available(app.db, 'SKU-KEYBOARD'), 4);
  assert.equal(await app.inventory.available(app.db, 'SKU-MOUSE'), 4);
});

it('[hidden] a successful order after a failed one reserves correctly', async () => {
  const app = await seededApp({ 'SKU-KEYBOARD': 3, 'SKU-MONITOR': 1 });
  await assert.rejects(
    app.orderService.placeOrder({
      customerId: 'c',
      items: [
        { sku: 'SKU-KEYBOARD', quantity: 2 },
        { sku: 'SKU-MONITOR', quantity: 2 },
      ],
    }),
  );
  await app.orderService.placeOrder({ customerId: 'c', items: [{ sku: 'SKU-KEYBOARD', quantity: 3 }] });
  assert.equal(await app.inventory.available(app.db, 'SKU-KEYBOARD'), 0);
});

it('[hidden] an unpriced item rolls back earlier reservations', async () => {
  const app = await seededApp({ 'SKU-KEYBOARD': 3, 'SKU-UNPRICED': 3 });
  await assert.rejects(
    app.orderService.placeOrder({
      customerId: 'c',
      items: [
        { sku: 'SKU-KEYBOARD', quantity: 1 },
        { sku: 'SKU-UNPRICED', quantity: 1 },
      ],
    }),
  );
  assert.equal(await app.inventory.available(app.db, 'SKU-KEYBOARD'), 3);
  assert.equal(await app.inventory.available(app.db, 'SKU-UNPRICED'), 3);
});
