import { randomUUID } from 'node:crypto';
import type { InMemoryDatabase } from '../db/database.ts';
import type { PaymentRecord } from '../domain/types.ts';
import { GatewayTimeoutError, type PaymentGateway } from '../gateways/paymentGateway.ts';
import { withRetry } from '../lib/retry.ts';

export class PaymentService {
  private readonly db: InMemoryDatabase;
  private readonly gateway: PaymentGateway;
  private readonly maxRetries: number;

  constructor(db: InMemoryDatabase, gateway: PaymentGateway, maxRetries = 3) {
    this.db = db;
    this.gateway = gateway;
    this.maxRetries = maxRetries;
  }

  /**
   * Captures a payment for an order. Gateway timeouts are retried because the
   * provider may simply have been slow to respond.
   */
  async capturePayment(orderId: string, amount: number): Promise<PaymentRecord> {
    const result = await withRetry(
      async () => {
        const idempotencyKey = randomUUID();
        return this.gateway.charge({ orderId, amount, idempotencyKey });
      },
      {
        retries: this.maxRetries,
        isRetryable: (error) => error instanceof GatewayTimeoutError,
      },
    );
    const record: PaymentRecord = {
      id: result.chargeId,
      orderId,
      amount: result.amount,
      status: 'captured',
    };
    await this.db.put('payments', record.id, { ...record });
    return record;
  }
}
