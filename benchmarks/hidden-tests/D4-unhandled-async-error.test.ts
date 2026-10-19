// Hidden evaluation test: copied to test/hidden/ in a disposable copy by the benchmark harness.
import assert from 'node:assert/strict';
import { it } from 'node:test';
import { FulfillmentError } from '../../src/domain/types.ts';
import { paidOrder, seededApp } from '../helpers.ts';

it('[hidden] all shipments exist by the time fulfill() resolves', async () => {
  const app = await seededApp();
  const order = await paidOrder(app, ['SKU-KEYBOARD', 'SKU-MOUSE', 'SKU-CABLE']);
  await app.fulfillmentService.fulfill(order.id);
  assert.equal(app.shippingGateway.shipments.length, 3);
});

it('[hidden] failure on the first item is reported as FulfillmentError', async () => {
  const app = await seededApp();
  const order = await paidOrder(app, ['SKU-MONITOR', 'SKU-CABLE']);
  app.shippingGateway.failFor('SKU-MONITOR');
  const unhandled: unknown[] = [];
  const onUnhandled = (reason: unknown) => unhandled.push(reason);
  process.on('unhandledRejection', onUnhandled);
  try {
    await assert.rejects(app.fulfillmentService.fulfill(order.id), FulfillmentError);
    await new Promise((resolve) => setTimeout(resolve, 10));
  } finally {
    process.off('unhandledRejection', onUnhandled);
  }
  assert.deepEqual(unhandled, []);
  assert.equal((await app.orderService.getOrder(order.id)).status, 'paid');
});
