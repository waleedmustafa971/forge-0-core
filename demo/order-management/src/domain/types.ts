export type OrderStatus =
  | 'pending'
  | 'paid'
  | 'shipped'
  | 'delivered'
  | 'cancelled'
  | 'refunded'
  | 'returned';

export interface OrderItem {
  sku: string;
  quantity: number;
  unitPrice: number;
}

export interface Order {
  id: string;
  customerId: string;
  status: OrderStatus;
  items: OrderItem[];
  total: number;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface InventoryRecord {
  sku: string;
  available: number;
}

export interface PaymentRecord {
  id: string;
  orderId: string;
  amount: number;
  status: 'captured';
}

export class DomainError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}

export class NotFoundError extends DomainError {}
export class InvalidTransitionError extends DomainError {}
export class InsufficientStockError extends DomainError {}
export class ValidationError extends DomainError {}
export class FulfillmentError extends DomainError {}
