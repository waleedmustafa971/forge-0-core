/** Yields to the event loop, simulating I/O latency of a real driver or remote call. */
export function tick(ms = 0): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
