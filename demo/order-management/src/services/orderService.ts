import { randomUUID } from 'node:crypto';
import type { InMemoryDatabase } from '../db/database.ts';
import { assertTransition } from '../domain/status.ts';
import { ValidationError, type Order, type OrderItem, type OrderStatus } from '../domain/types.ts';
import type { PricingClient } from '../gateways/pricing.ts';
import type { InventoryRepository } from '../repositories/inventoryRepository.ts';
import type { OrderRepository } from '../repositories/orderRepository.ts';

export interface NewOrderItem {
  sku: string;
  quantity: number;
}

export interface PlaceOrderInput {
  customerId: string;
  items: NewOrderItem[];
}

export function computeTotal(items: OrderItem[]): number {
  return Math.round(items.reduce((sum, item) => sum + item.unitPrice * item.quantity, 0) * 100) / 100;
}

function validateItems(items: NewOrderItem[]): void {
  if (items.length === 0) throw new ValidationError('An order needs at least one item');
  for (const item of items) {
    if (!Number.isInteger(item.quantity) || item.quantity <= 0) {
      throw new ValidationError(`Invalid quantity for ${item.sku}: ${item.quantity}`);
    }
  }
}

export class OrderService {
  private readonly db: InMemoryDatabase;
  private readonly orders: OrderRepository;
  private readonly inventory: InventoryRepository;
  private readonly pricing: PricingClient;

  constructor(
    db: InMemoryDatabase,
    orders: OrderRepository,
    inventory: InventoryRepository,
    pricing: PricingClient,
  ) {
    this.db = db;
    this.orders = orders;
    this.inventory = inventory;
    this.pricing = pricing;
  }

  /** Creates a pending order and reserves stock for every line item atomically. */
  async placeOrder(input: PlaceOrderInput): Promise<Order> {
    validateItems(input.items);
    return this.db.transaction(async (tx) => {
      const items: OrderItem[] = [];
      for (const item of input.items) {
        await this.inventory.reserve(this.db, item.sku, item.quantity);
        items.push({ ...item, unitPrice: await this.pricing.priceFor(item.sku) });
      }
      const now = new Date().toISOString();
      const order: Order = {
        id: randomUUID(),
        customerId: input.customerId,
        status: 'pending',
        items,
        total: computeTotal(items),
        version: 1,
        createdAt: now,
        updatedAt: now,
      };
      await this.orders.insert(tx, order);
      return order;
    });
  }

  async getOrder(id: string): Promise<Order> {
    return this.orders.get(this.db, id);
  }

  /** Adds a line item to an existing pending order. */
  async addItem(orderId: string, item: NewOrderItem): Promise<Order> {
    validateItems([item]);
    const order = await this.orders.get(this.db, orderId);
    if (order.status !== 'pending') {
      throw new ValidationError(`Order ${orderId} can no longer be modified`);
    }
    const unitPrice = await this.pricing.priceFor(item.sku);
    order.items.push({ ...item, unitPrice });
    order.total = computeTotal(order.items);
    order.version += 1;
    await this.orders.update(this.db, order);
    return order;
  }

  async transition(orderId: string, next: OrderStatus): Promise<Order> {
    const order = await this.orders.get(this.db, orderId);
    assertTransition(order.status, next);
    order.status = next;
    order.version += 1;
    await this.orders.update(this.db, order);
    return order;
  }

  async cancel(orderId: string): Promise<Order> {
    return this.transition(orderId, 'cancelled');
  }
}
