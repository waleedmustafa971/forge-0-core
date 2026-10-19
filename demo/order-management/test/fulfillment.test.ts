import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { FulfillmentError, InvalidTransitionError } from '../src/domain/types.ts';
import { tick } from '../src/lib/async.ts';
import { paidOrder, seededApp } from './helpers.ts';

describe('fulfillment', () => {
  it('ships every item of a paid order', async () => {
    const app = await seededApp();
    const order = await paidOrder(app, ['SKU-KEYBOARD', 'SKU-MOUSE', 'SKU-CABLE']);
    const shipped = await app.fulfillmentService.fulfill(order.id);
    assert.equal(shipped.status, 'shipped');
    await tick(10);
    assert.equal(app.shippingGateway.shipments.length, 3);
    assert.equal((await app.orderService.getOrder(order.id)).status, 'shipped');
  });

  it('refuses to fulfill an unpaid order', async () => {
    const app = await seededApp();
    const order = await app.orderService.placeOrder({
      customerId: 'cust-1',
      items: [{ sku: 'SKU-KEYBOARD', quantity: 1 }],
    });
    await assert.rejects(app.fulfillmentService.fulfill(order.id), InvalidTransitionError);
  });

  it('reports carrier failures and does not mark the order as shipped', async () => {
    const app = await seededApp();
    const order = await paidOrder(app, ['SKU-KEYBOARD', 'SKU-MONITOR']);
    app.shippingGateway.failFor('SKU-MONITOR');
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown) => unhandled.push(reason);
    process.on('unhandledRejection', onUnhandled);
    try {
      await assert.rejects(app.fulfillmentService.fulfill(order.id), FulfillmentError);
      await tick(10);
    } finally {
      process.off('unhandledRejection', onUnhandled);
    }
    assert.deepEqual(unhandled, [], 'shipment errors must not escape as unhandled rejections');
    assert.equal((await app.orderService.getOrder(order.id)).status, 'paid');
  });
});
