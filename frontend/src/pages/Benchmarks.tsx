import { formatDate } from '../format';
import { useState } from 'react';
import { api } from '../api/client';
import { Card, Empty, Spinner } from '../components/ui';
import { useAsync } from '../hooks';

interface SystemMetrics {
  investigation_id: string | null;
  verdict: string | null;
  reproduced: boolean | null;
  claimed_fixed: boolean;
  verifier_verdict: string | null;
  hidden_tests_passed: boolean | null;
  actually_fixed: boolean;
  regressions: number;
  false_positive: boolean;
  experiments: number;
  patch_attempts: number;
  duration_s: number;
  model_calls: number;
  total_tokens: number;
  tokens_estimated: boolean;
  estimated_cost_usd: number;
  error?: string | null;
}

interface Aggregate {
  scenarios: number;
  reproduction_rate: number;
  verified_repair_rate: number;
  regression_failures: number;
  false_positive_rate: number;
  false_positives: number;
  claimed_fixes: number;
  mean_experiments: number;
  total_duration_s: number;
  total_tokens: number;
  estimated_cost_usd: number;
}

interface BenchmarkResult {
  run_id: string;
  created_at: string;
  provider: string;
  model: string;
  simulated: boolean;
  disclaimer: string;
  scenarios: { defect: string; title: string; target_test: string; systems: Record<'baseline' | 'forge', SystemMetrics> }[];
  aggregate: Record<'baseline' | 'forge', Aggregate>;
}

const SYSTEMS = [
  { id: 'baseline', name: 'Baseline A · one-shot', color: 'var(--text-muted)' },
  { id: 'forge', name: 'System B · FORGE-0', color: 'var(--accent)' },
] as const;

function Bars({ label, values, format, max }: { label: string; values: Record<string, number>; format: (v: number) => string; max?: number }) {
  const top = max ?? Math.max(...Object.values(values), 1e-9);
  return (
    <div className="stack-sm">
      <div className="label">{label}</div>
      <div className="bar-chart">
        {SYSTEMS.map((s) => (
          <div className="bar-row" key={s.id}>
            <span className="small">{s.name}</span>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${Math.min(100, ((values[s.id] ?? 0) / top) * 100)}%`, background: s.color }} />
            </div>
            <span className="mono small">{format(values[s.id] ?? 0)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const pct = (v: number) => `${Math.round(v * 100)}%`;
const yes = (v: boolean | null) => (v == null ? '—' : v ? '✔' : '✘');

export default function Benchmarks() {
  const runs = useAsync(() => api.benchmarks(), []);
  const [selected, setSelected] = useState<string>('latest');
  const result = useAsync(
    () => (runs.data?.runs.length ? (api.benchmark(selected) as unknown as Promise<BenchmarkResult>) : Promise.resolve(null)),
    [selected, runs.data?.runs.length],
  );
  const r = result.data;

  return (
    <div className="stack fade-in">
      <div className="page-header">
        <div>
          <h1>Evaluation</h1>
          <p>Baseline A (direct one-shot repair) versus System B (FORGE-0 hypothesis-driven debugging) on the demo defects.</p>
        </div>
        {runs.data?.runs.length ? (
          <select className="select" style={{ width: 280 }} value={selected} onChange={(e) => setSelected(e.target.value)}>
            <option value="latest">Latest run</option>
            {runs.data.runs.map((run) => (
              <option key={run.file} value={run.file}>
                {run.run_id} · {run.provider}
                {run.simulated ? ' (mock)' : ''}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      {runs.loading ? (
        <Spinner />
      ) : !runs.data?.runs.length ? (
        <Card>
          <Empty>
            No benchmark results yet. Run <code>python benchmarks/run_benchmark.py</code> from the repository root.
          </Empty>
        </Card>
      ) : !r ? (
        <Spinner />
      ) : (
        <>
          <div className={`alert ${r.simulated ? 'amber' : 'blue'} small`}>
            <strong>{r.simulated ? 'Mock-only evaluation.' : 'Real-model evaluation.'}</strong>
            <span>{r.disclaimer}</span>
          </div>
          <div className="row small muted">
            run <code>{r.run_id}</code> · {formatDate(r.created_at)} · provider {r.provider}/{r.model} · {r.scenarios.length} scenarios
          </div>
          <div className="grid grid-2">
            <Card title="Outcomes">
              <div className="stack">
                <Bars label="Verified repair rate (hidden-test confirmed)" values={{ baseline: r.aggregate.baseline.verified_repair_rate, forge: r.aggregate.forge.verified_repair_rate }} format={pct} max={1} />
                <Bars label="Reproduction rate" values={{ baseline: r.aggregate.baseline.reproduction_rate, forge: r.aggregate.forge.reproduction_rate }} format={pct} max={1} />
                <Bars label="False-positive repair rate (claimed but not fixed)" values={{ baseline: r.aggregate.baseline.false_positive_rate, forge: r.aggregate.forge.false_positive_rate }} format={pct} max={1} />
                <Bars label="Claimed fixes with regressions" values={{ baseline: r.aggregate.baseline.regression_failures, forge: r.aggregate.forge.regression_failures }} format={(v) => String(v)} />
              </div>
            </Card>
            <Card title="Cost of evidence">
              <div className="stack">
                <Bars label="Mean experiments per defect" values={{ baseline: r.aggregate.baseline.mean_experiments, forge: r.aggregate.forge.mean_experiments }} format={(v) => v.toFixed(1)} />
                <Bars label="Total wall time (s)" values={{ baseline: r.aggregate.baseline.total_duration_s, forge: r.aggregate.forge.total_duration_s }} format={(v) => v.toFixed(0)} />
                <Bars label={`Total tokens${r.simulated ? ' (estimated)' : ''}`} values={{ baseline: r.aggregate.baseline.total_tokens, forge: r.aggregate.forge.total_tokens }} format={(v) => v.toLocaleString()} />
                <Bars label={`Estimated API cost (USD${r.simulated ? ', hypothetical' : ''})`} values={{ baseline: r.aggregate.baseline.estimated_cost_usd, forge: r.aggregate.forge.estimated_cost_usd }} format={(v) => `$${v.toFixed(4)}`} />
              </div>
            </Card>
          </div>
          <Card title="Per-defect results" flush>
            <table className="table">
              <thead>
                <tr>
                  <th>Defect</th>
                  <th>System</th>
                  <th>Reproduced</th>
                  <th>Claimed fix</th>
                  <th>Verifier</th>
                  <th>Hidden tests</th>
                  <th>Actually fixed</th>
                  <th>Experiments</th>
                  <th>Patches</th>
                  <th>Time</th>
                </tr>
              </thead>
              <tbody>
                {r.scenarios.flatMap((sc) =>
                  SYSTEMS.map((sys, i) => {
                    const m = sc.systems[sys.id];
                    return (
                      <tr key={`${sc.defect}-${sys.id}`}>
                        {i === 0 && (
                          <td rowSpan={2}>
                            <div className="mono small">{sc.defect}</div>
                            <div className="faint small">{sc.title}</div>
                          </td>
                        )}
                        <td className="small">{sys.name}</td>
                        <td>{yes(m.reproduced)}</td>
                        <td>{yes(m.claimed_fixed)}</td>
                        <td className="small">{m.verifier_verdict ?? '—'}</td>
                        <td>{yes(m.hidden_tests_passed)}</td>
                        <td>
                          <span className={`badge ${m.actually_fixed ? 'green' : m.false_positive ? 'red' : 'outline'}`}>
                            {m.actually_fixed ? 'fixed' : m.false_positive ? 'false positive' : 'not fixed'}
                          </span>
                        </td>
                        <td className="mono small">{m.experiments}</td>
                        <td className="mono small">{m.patch_attempts}</td>
                        <td className="mono small">{m.duration_s.toFixed(1)}s</td>
                      </tr>
                    );
                  }),
                )}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}
