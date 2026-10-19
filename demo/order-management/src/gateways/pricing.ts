import { tick } from '../lib/async.ts';

export interface PricingClient {
  priceFor(sku: string): Promise<number>;
}

/** Static price list standing in for a remote pricing service. */
export class StaticPricingClient implements PricingClient {
  private readonly prices: Record<string, number>;
  private readonly latencyMs: number;

  constructor(prices: Record<string, number>, latencyMs = 2) {
    this.prices = prices;
    this.latencyMs = latencyMs;
  }

  async priceFor(sku: string): Promise<number> {
    await tick(this.latencyMs);
    const price = this.prices[sku];
    if (price === undefined) throw new Error(`No price for ${sku}`);
    return price;
  }
}
