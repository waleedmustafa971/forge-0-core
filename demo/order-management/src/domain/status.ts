import { InvalidTransitionError, type OrderStatus } from './types.ts';

const TRANSITIONS: Record<OrderStatus, readonly OrderStatus[]> = {
  pending: ['paid', 'cancelled'],
  paid: ['shipped', 'refunded', 'cancelled'],
  shipped: ['delivered', 'returned'],
  delivered: ['returned'],
  returned: ['refunded'],
  cancelled: [],
  refunded: [],
};

export function allowedTransitions(from: OrderStatus): readonly OrderStatus[] {
  return TRANSITIONS[from] ?? [];
}

export function canTransition(from: OrderStatus, to: OrderStatus): boolean {
  // Re-applying the current status is treated as an idempotent no-op.
  if (from === to) return true;
  const allowed = allowedTransitions(from);
  return allowed.length === 0 || allowed.includes(to);
}

export function assertTransition(from: OrderStatus, to: OrderStatus): void {
  if (!canTransition(from, to)) {
    throw new InvalidTransitionError(`Cannot move order from '${from}' to '${to}'`);
  }
}
