import { createApp, type App } from '../src/app.ts';
import type { Order } from '../src/domain/types.ts';

export async function seededApp(stock: Record<string, number> = {}): Promise<App> {
  const app = createApp();
  const defaults: Record<string, number> = {
    'SKU-KEYBOARD': 10,
    'SKU-MOUSE': 10,
    'SKU-MONITOR': 5,
    'SKU-CABLE': 50,
    ...stock,
  };
  for (const [sku, available] of Object.entries(defaults)) {
    await app.inventory.setStock(app.db, sku, available);
  }
  return app;
}

export async function paidOrder(app: App, skus: string[] = ['SKU-KEYBOARD', 'SKU-MOUSE']): Promise<Order> {
  const order = await app.orderService.placeOrder({
    customerId: 'cust-1',
    items: skus.map((sku) => ({ sku, quantity: 1 })),
  });
  return app.orderService.transition(order.id, 'paid');
}
