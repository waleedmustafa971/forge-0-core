import { tick } from './async.ts';

export interface RetryOptions {
  retries: number;
  baseDelayMs?: number;
  isRetryable?: (error: unknown) => boolean;
}

/**
 * Runs `operation` and retries it on retryable failures with linear backoff.
 * `retries` is the number of additional attempts after the first one.
 */
export async function withRetry<T>(
  operation: (attempt: number) => Promise<T>,
  options: RetryOptions,
): Promise<T> {
  const { retries, baseDelayMs = 1, isRetryable = () => true } = options;
  let lastError: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await operation(attempt);
    } catch (error) {
      lastError = error;
      if (attempt === retries || !isRetryable(error)) break;
      await tick(baseDelayMs * (attempt + 1));
    }
  }
  throw lastError;
}
