import type { InMemoryDatabase } from '../db/database.ts';
import { assertTransition } from '../domain/status.ts';
import { FulfillmentError, type Order } from '../domain/types.ts';
import type { ShippingGateway } from '../gateways/shippingGateway.ts';
import type { OrderRepository } from '../repositories/orderRepository.ts';

export class FulfillmentService {
  private readonly db: InMemoryDatabase;
  private readonly orders: OrderRepository;
  private readonly shipping: ShippingGateway;

  constructor(db: InMemoryDatabase, orders: OrderRepository, shipping: ShippingGateway) {
    this.db = db;
    this.orders = orders;
    this.shipping = shipping;
  }

  /** Books a shipment for every line item, then marks the order as shipped. */
  async fulfill(orderId: string): Promise<Order> {
    const order = await this.orders.get(this.db, orderId);
    assertTransition(order.status, 'shipped');
    try {
      order.items.forEach(async (item) => {
        await this.shipping.createShipment(order.id, item);
      });
    } catch (error) {
      throw new FulfillmentError(`Fulfillment failed for order ${order.id}: ${String(error)}`);
    }
    order.status = 'shipped';
    order.version += 1;
    await this.orders.update(this.db, order);
    return order;
  }
}
