import { InMemoryDatabase } from './db/database.ts';
import { FakePaymentGateway } from './gateways/paymentGateway.ts';
import { StaticPricingClient } from './gateways/pricing.ts';
import { FakeShippingGateway } from './gateways/shippingGateway.ts';
import { InventoryRepository } from './repositories/inventoryRepository.ts';
import { OrderRepository } from './repositories/orderRepository.ts';
import { FulfillmentService } from './services/fulfillmentService.ts';
import { OrderService } from './services/orderService.ts';
import { PaymentService } from './services/paymentService.ts';

export const DEFAULT_PRICES: Record<string, number> = {
  'SKU-KEYBOARD': 49.5,
  'SKU-MOUSE': 19.99,
  'SKU-MONITOR': 189,
  'SKU-CABLE': 7.25,
};

/** Wires the service graph with in-process fakes. */
export function createApp(prices: Record<string, number> = DEFAULT_PRICES) {
  const db = new InMemoryDatabase();
  const orders = new OrderRepository();
  const inventory = new InventoryRepository();
  const pricing = new StaticPricingClient(prices);
  const paymentGateway = new FakePaymentGateway();
  const shippingGateway = new FakeShippingGateway();
  return {
    db,
    orders,
    inventory,
    pricing,
    paymentGateway,
    shippingGateway,
    orderService: new OrderService(db, orders, inventory, pricing),
    paymentService: new PaymentService(db, paymentGateway),
    fulfillmentService: new FulfillmentService(db, orders, shippingGateway),
  };
}

export type App = ReturnType<typeof createApp>;
