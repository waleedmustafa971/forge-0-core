import { useState } from 'react';
import type { Experiment } from '../../api/types';
import { DiffViewer } from '../../components/DiffViewer';
import { Card, Empty, OutcomeBadge } from '../../components/ui';
import { formatTime } from '../../format';
import type { LiveInvestigation } from '../../hooks';

function ExperimentDetail({ e }: { e: Experiment }) {
  const [tab, setTab] = useState<'evidence' | 'code' | 'output'>('evidence');
  const tests = e.result?.test_run?.tests ?? [];
  return (
    <div className="stack-sm" style={{ marginTop: 10 }}>
      <div className="row">
        {(['evidence', 'code', 'output'] as const).map((t) => (
          <button key={t} className={`btn sm ${tab === t ? '' : 'ghost'}`} onClick={() => setTab(t)}>
            {t === 'evidence' ? 'Predictions & evidence' : t === 'code' ? 'Experiment code' : 'Raw output'}
          </button>
        ))}
      </div>
      {tab === 'evidence' && (
        <div className="stack-sm">
          {e.evaluation?.errors && (
            <div className="alert red small">Rejected before execution: {e.evaluation.errors.join('; ')}</div>
          )}
          {e.predictions.length > 0 && (
            <table className="table" style={{ border: '1px solid var(--border)', borderRadius: 6 }}>
              <thead>
                <tr>
                  <th>Hypothesis</th>
                  <th>Predicted</th>
                  <th>Observed</th>
                  <th>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {e.predictions.map((p) => {
                  const ev = e.evaluation?.predictions?.find((x) => x.hypothesis === p.hypothesis);
                  return (
                    <tr key={p.hypothesis}>
                      <td className="mono">{p.hypothesis}</td>
                      <td>
                        {p.outcome}
                        {p.output_contains && <div className="faint small">output contains “{p.output_contains}”</div>}
                        {p.rationale && <div className="faint small">{p.rationale}</div>}
                      </td>
                      <td>{ev?.observed ?? '—'}</td>
                      <td>
                        {ev ? (
                          <span className={`badge ${ev.matched ? 'green' : 'red'}`}>{ev.matched ? 'consistent' : 'contradicted'}</span>
                        ) : (
                          <span className="faint small">no evidence</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {e.evaluation?.belief_before && e.evaluation.belief_after && (
            <div className="row wrap small">
              <span className="label">Ranking update</span>
              {Object.entries(e.evaluation.belief_after.hypotheses).map(([k, after]) => {
                const before = e.evaluation!.belief_before!.hypotheses[k] ?? 0;
                return (
                  <span key={k} className="mono">
                    {k} {before.toFixed(2)}→
                    <span style={{ color: after > before ? 'var(--green)' : after < before ? 'var(--red)' : undefined }}>
                      {after.toFixed(2)}
                    </span>
                  </span>
                );
              })}
            </div>
          )}
          {tests.length > 0 && (
            <div className="small">
              {tests.map((t) => (
                <div key={t.name} className="row" style={{ alignItems: 'flex-start' }}>
                  <span className="dot" style={{ marginTop: 7, color: t.status === 'passed' ? 'var(--green)' : t.status === 'failed' ? 'var(--red)' : 'var(--text-faint)' }} />
                  <div>
                    <div>{t.name}</div>
                    {t.error && <div className="mono faint small">{t.error_name}: {t.error.split('\n')[0]}</div>}
                  </div>
                </div>
              ))}
            </div>
          )}
          {e.spec.success_condition && (
            <div className="small muted">
              <strong>Success:</strong> {e.spec.success_condition} · <strong>Failure:</strong> {e.spec.failure_condition}
            </div>
          )}
        </div>
      )}
      {tab === 'code' && (
        <div className="stack-sm">
          {e.spec.files?.map((f) => (
            <div key={f.path}>
              <div className="mono small faint" style={{ marginBottom: 4 }}>{f.path}</div>
              <pre className="code">{f.content}</pre>
            </div>
          ))}
          {e.evaluation?.intervention_diff && (
            <div>
              <div className="label" style={{ marginBottom: 4 }}>Counterfactual intervention (disposable copy only)</div>
              <DiffViewer diff={e.evaluation.intervention_diff} />
            </div>
          )}
          <div className="mono small muted">
            run: {e.spec.run?.join(' ')} {e.spec.test_name_pattern ? `--test-name-pattern=${e.spec.test_name_pattern}` : ''}
          </div>
          {!e.spec.files?.length && !e.evaluation?.intervention_diff && <span className="faint small">Re-runs existing tests.</span>}
        </div>
      )}
      {tab === 'output' && e.result && (
        <div className="stack-sm">
          <div className="mono small muted">
            $ {e.result.command.join(' ')} · exit {String(e.result.exit_code)} · {e.result.duration_ms} ms · {e.result.image}
            {e.result.timed_out ? ' · TIMED OUT' : ''}
          </div>
          <div className="row wrap small">
            {Object.entries(e.result.sandbox).map(([k, v]) => (
              <span key={k} className="badge outline">
                {k}: {String(v)}
              </span>
            ))}
          </div>
          <pre className="code">{e.result.stdout || '(no stdout)'}</pre>
          {e.result.stderr && <pre className="code" style={{ color: 'var(--text-muted)' }}>{e.result.stderr}</pre>}
        </div>
      )}
    </div>
  );
}

export default function Timeline({ live }: { live: LiveInvestigation }) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  if (!live.experiments.length) return <Empty>No experiments have been designed yet.</Empty>;
  return (
    <Card title="Experiment timeline">
      <div className="timeline">
        {live.experiments.map((e, i) => {
          const color =
            e.outcome === 'pass' ? 'var(--green)' : e.outcome === 'fail' ? 'var(--red)' : e.status === 'running' ? 'var(--accent)' : 'var(--yellow)';
          const open = openKey === e.id;
          return (
            <div className="timeline-item fade-in" key={e.id}>
              <div className="timeline-marker">
                <div className="node" style={{ color, borderColor: color }}>
                  {e.key}
                </div>
                {i < live.experiments.length - 1 && <div className="line" />}
              </div>
              <div style={{ paddingBottom: 6, minWidth: 0 }}>
                <div className="row wrap">
                  <strong>{e.objective}</strong>
                  <OutcomeBadge outcome={e.outcome} status={e.status} />
                  <span className="badge outline">{e.kind}</span>
                  {e.spec.discriminating === false && <span className="badge yellow">non-discriminating</span>}
                  {e.round > 0 && <span className="faint small">round {e.round}</span>}
                  <span className="spacer" />
                  <span className="faint small">
                    {formatTime(e.started_at)}
                    {e.result ? ` · ${e.result.duration_ms} ms` : ''}
                  </span>
                  <button className="btn ghost sm" onClick={() => setOpenKey(open ? null : e.id)}>
                    {open ? 'Hide' : 'Evidence'}
                  </button>
                </div>
                <div className="muted small">
                  {e.designed_by === 'investigator' ? 'Control run by the Repository Investigator' : `Tests ${e.hypothesis_keys.join(', ')}`}
                  {e.evaluation?.detail ? ` · ${e.evaluation.detail}` : ''}
                </div>
                {open && <ExperimentDetail e={e} />}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
