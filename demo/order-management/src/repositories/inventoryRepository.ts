import type { DbHandle } from '../db/database.ts';
import { InsufficientStockError, type InventoryRecord } from '../domain/types.ts';

const TABLE = 'inventory';

export class InventoryRepository {
  async setStock(db: DbHandle, sku: string, available: number): Promise<void> {
    await db.put(TABLE, sku, { sku, available });
  }

  async available(db: DbHandle, sku: string): Promise<number> {
    const record = (await db.get(TABLE, sku)) as InventoryRecord | undefined;
    return record?.available ?? 0;
  }

  /** Decrements stock for `sku`, failing if not enough units are available. */
  async reserve(db: DbHandle, sku: string, quantity: number): Promise<void> {
    const available = await this.available(db, sku);
    if (available < quantity) {
      throw new InsufficientStockError(
        `Insufficient stock for ${sku}: requested ${quantity}, available ${available}`,
      );
    }
    await db.put(TABLE, sku, { sku, available: available - quantity });
  }
}
