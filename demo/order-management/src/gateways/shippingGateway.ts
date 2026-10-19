import { tick } from '../lib/async.ts';
import type { OrderItem } from '../domain/types.ts';

export interface Shipment {
  shipmentId: string;
  orderId: string;
  sku: string;
  quantity: number;
}

export class CarrierUnavailableError extends Error {
  constructor(message = 'Carrier unavailable') {
    super(message);
    this.name = 'CarrierUnavailableError';
  }
}

export interface ShippingGateway {
  createShipment(orderId: string, item: OrderItem): Promise<Shipment>;
}

export class FakeShippingGateway implements ShippingGateway {
  readonly shipments: Shipment[] = [];
  private readonly failingSkus = new Set<string>();

  failFor(sku: string): void {
    this.failingSkus.add(sku);
  }

  async createShipment(orderId: string, item: OrderItem): Promise<Shipment> {
    await tick(5);
    if (this.failingSkus.has(item.sku)) {
      throw new CarrierUnavailableError(`Carrier rejected shipment for ${item.sku}`);
    }
    const shipment = {
      shipmentId: `sh_${this.shipments.length + 1}`,
      orderId,
      sku: item.sku,
      quantity: item.quantity,
    };
    this.shipments.push(shipment);
    return shipment;
  }
}
