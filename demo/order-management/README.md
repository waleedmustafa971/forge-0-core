# order-management

A small order-management service: checkout with stock reservation, line-item edits,
payment capture with retries, fulfillment, and an order status lifecycle.

Written in TypeScript with zero runtime dependencies. Node.js 22.18+ runs the `.ts`
sources directly through native type stripping.

```bash
npm test            # node --test "test/**/*.test.ts"
npm run typecheck   # requires `npm install` for the TypeScript compiler
```

## Layout

| Path | Purpose |
| --- | --- |
| `src/db/database.ts` | In-memory async database with transactions |
| `src/domain/` | Types and the status state machine |
| `src/repositories/` | Data access for orders and inventory |
| `src/services/` | Order, payment and fulfillment services |
| `src/gateways/` | Pricing, payment and shipping clients (in-process fakes) |
| `src/lib/` | Retry and async helpers |
