import { render, screen } from '@testing-library/react';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Benchmarks from './Benchmarks';

const resultsDir = join(__dirname, '../../../benchmarks/results');
const latest = readdirSync(resultsDir).filter((f) => f.endsWith('.json')).sort().pop()!;
const result = JSON.parse(readFileSync(join(resultsDir, latest), 'utf-8'));

afterEach(() => vi.unstubAllGlobals());

describe('Benchmarks page', () => {
  it('renders the latest benchmark result without looping', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const body = url.endsWith('/benchmarks')
        ? { runs: [{ file: latest, run_id: result.run_id, created_at: result.created_at, provider: result.provider, simulated: result.simulated }] }
        : result;
      return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });
    });
    vi.stubGlobal('fetch', fetchMock);
    render(
      <MemoryRouter>
        <Benchmarks />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/Per-defect results/)).toBeInTheDocument();
    expect(screen.getByText(/Mock-only evaluation/)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 200));
    expect(fetchMock.mock.calls.length).toBeLessThan(6);
  });
});
