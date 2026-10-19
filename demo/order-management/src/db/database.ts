import { tick } from '../lib/async.ts';

type Row = Record<string, unknown>;
type Shape = object;

/** Minimal handle shared by the root connection and transactions. */
export interface DbHandle {
  get<T extends Shape>(table: string, id: string): Promise<T | undefined>;
  put<T extends Shape>(table: string, id: string, row: T): Promise<void>;
  delete(table: string, id: string): Promise<void>;
  list<T extends Shape>(table: string): Promise<T[]>;
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

/**
 * In-memory asynchronous database used by the service and its tests.
 * Every operation yields to the event loop, like a network driver would.
 */
export class InMemoryDatabase implements DbHandle {
  private readonly tables = new Map<string, Map<string, Row>>();

  private table(name: string): Map<string, Row> {
    let table = this.tables.get(name);
    if (!table) {
      table = new Map();
      this.tables.set(name, table);
    }
    return table;
  }

  async get<T extends Shape>(table: string, id: string): Promise<T | undefined> {
    await tick();
    const row = this.table(table).get(id);
    return row === undefined ? undefined : (clone(row) as unknown as T);
  }

  async put<T extends Shape>(table: string, id: string, row: T): Promise<void> {
    await tick();
    this.table(table).set(id, clone(row) as Row);
  }

  async delete(table: string, id: string): Promise<void> {
    await tick();
    this.table(table).delete(id);
  }

  async list<T extends Shape>(table: string): Promise<T[]> {
    await tick();
    return [...this.table(table).values()].map((row) => clone(row) as unknown as T);
  }

  /**
   * Runs `work` inside a transaction. Writes made through the transaction handle
   * are buffered and applied atomically on success, or discarded if `work` throws.
   */
  async transaction<T>(work: (tx: Transaction) => Promise<T>): Promise<T> {
    const tx = new Transaction(this);
    try {
      const result = await work(tx);
      await tx.commit();
      return result;
    } catch (error) {
      tx.rollback();
      throw error;
    }
  }

  /** @internal applies a batch of committed writes. */
  applyCommitted(writes: Map<string, Map<string, Row | null>>): void {
    for (const [tableName, rows] of writes) {
      const table = this.table(tableName);
      for (const [id, row] of rows) {
        if (row === null) table.delete(id);
        else table.set(id, clone(row));
      }
    }
  }
}

export class Transaction implements DbHandle {
  private readonly writes = new Map<string, Map<string, Row | null>>();
  private state: 'open' | 'committed' | 'rolled_back' = 'open';

  private readonly db: InMemoryDatabase;

  constructor(db: InMemoryDatabase) {
    this.db = db;
  }

  private pending(table: string): Map<string, Row | null> {
    let rows = this.writes.get(table);
    if (!rows) {
      rows = new Map();
      this.writes.set(table, rows);
    }
    return rows;
  }

  private ensureOpen(): void {
    if (this.state !== 'open') throw new Error(`Transaction is ${this.state}`);
  }

  async get<T extends Shape>(table: string, id: string): Promise<T | undefined> {
    this.ensureOpen();
    const rows = this.writes.get(table);
    if (rows?.has(id)) {
      await tick();
      const row = rows.get(id);
      return row === null || row === undefined ? undefined : (clone(row) as unknown as T);
    }
    return this.db.get<T>(table, id);
  }

  async put<T extends Shape>(table: string, id: string, row: T): Promise<void> {
    this.ensureOpen();
    await tick();
    this.pending(table).set(id, clone(row) as Row);
  }

  async delete(table: string, id: string): Promise<void> {
    this.ensureOpen();
    await tick();
    this.pending(table).set(id, null);
  }

  async list<T extends Shape>(table: string): Promise<T[]> {
    this.ensureOpen();
    const committed = await this.db.list<T>(table);
    const rows = this.writes.get(table);
    if (!rows) return committed;
    const merged = new Map<string, T>(
      committed.map((row) => {
        const r = row as Row;
        return [String(r.id ?? r.sku), row];
      }),
    );
    for (const [id, row] of rows) {
      if (row === null) merged.delete(id);
      else merged.set(id, clone(row) as unknown as T);
    }
    return [...merged.values()];
  }

  async commit(): Promise<void> {
    this.ensureOpen();
    await tick();
    this.db.applyCommitted(this.writes);
    this.state = 'committed';
  }

  rollback(): void {
    if (this.state !== 'open') return;
    this.writes.clear();
    this.state = 'rolled_back';
  }
}
