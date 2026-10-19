import type { DbHandle } from '../db/database.ts';
import { NotFoundError, type Order } from '../domain/types.ts';

const TABLE = 'orders';

export class OrderRepository {
  async insert(db: DbHandle, order: Order): Promise<void> {
    await db.put(TABLE, order.id, { ...order });
  }

  async find(db: DbHandle, id: string): Promise<Order | undefined> {
    return (await db.get(TABLE, id)) as Order | undefined;
  }

  async get(db: DbHandle, id: string): Promise<Order> {
    const order = await this.find(db, id);
    if (!order) throw new NotFoundError(`Order ${id} not found`);
    return order;
  }

  async update(db: DbHandle, order: Order): Promise<void> {
    await db.put(TABLE, order.id, { ...order, updatedAt: new Date().toISOString() });
  }

  async list(db: DbHandle): Promise<Order[]> {
    return (await db.list(TABLE)) as unknown as Order[];
  }
}
