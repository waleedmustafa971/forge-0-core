// Hidden evaluation test: copied to test/hidden/ in a disposable copy by the benchmark harness.
import assert from 'node:assert/strict';
import { it } from 'node:test';
import { canTransition } from '../../src/domain/status.ts';
import type { OrderStatus } from '../../src/domain/types.ts';

const ALL: OrderStatus[] = ['pending', 'paid', 'shipped', 'delivered', 'cancelled', 'refunded', 'returned'];

it('[hidden] terminal statuses reject every other transition', () => {
  for (const terminal of ['cancelled', 'refunded'] as const) {
    for (const to of ALL) {
      assert.equal(canTransition(terminal, to), to === terminal, `${terminal} -> ${to}`);
    }
  }
});

it('[hidden] non-terminal statuses keep their documented transitions', () => {
  assert.equal(canTransition('pending', 'paid'), true);
  assert.equal(canTransition('paid', 'refunded'), true);
  assert.equal(canTransition('returned', 'refunded'), true);
  assert.equal(canTransition('delivered', 'paid'), false);
});
