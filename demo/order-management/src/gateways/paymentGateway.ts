import { tick } from '../lib/async.ts';

export interface ChargeRequest {
  orderId: string;
  amount: number;
  idempotencyKey: string;
}

export interface ChargeResult {
  chargeId: string;
  orderId: string;
  amount: number;
}

export class GatewayTimeoutError extends Error {
  constructor(message = 'Payment gateway timed out') {
    super(message);
    this.name = 'GatewayTimeoutError';
  }
}

export class CardDeclinedError extends Error {
  constructor(message = 'Card declined') {
    super(message);
    this.name = 'CardDeclinedError';
  }
}

export interface PaymentGateway {
  charge(request: ChargeRequest): Promise<ChargeResult>;
}

/**
 * In-process payment gateway used in tests. It honours idempotency keys like a
 * real provider: repeating a request with the same key returns the original
 * charge instead of creating a new one.
 */
export class FakePaymentGateway implements PaymentGateway {
  readonly charges: ChargeResult[] = [];
  readonly requests: ChargeRequest[] = [];
  private readonly byKey = new Map<string, ChargeResult>();
  private timeoutsAfterProcessing = 0;
  private declineNext = false;

  /** The next `count` requests are processed but the response is lost (timeout). */
  failNextResponses(count: number): void {
    this.timeoutsAfterProcessing = count;
  }

  declineNextCharge(): void {
    this.declineNext = true;
  }

  async charge(request: ChargeRequest): Promise<ChargeResult> {
    await tick();
    this.requests.push(request);
    if (this.declineNext) {
      this.declineNext = false;
      throw new CardDeclinedError();
    }
    let result = this.byKey.get(request.idempotencyKey);
    if (!result) {
      result = {
        chargeId: `ch_${this.charges.length + 1}`,
        orderId: request.orderId,
        amount: request.amount,
      };
      this.byKey.set(request.idempotencyKey, result);
      this.charges.push(result);
    }
    if (this.timeoutsAfterProcessing > 0) {
      this.timeoutsAfterProcessing--;
      throw new GatewayTimeoutError();
    }
    return result;
  }
}
