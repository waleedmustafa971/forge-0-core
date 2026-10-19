import { Link } from 'react-router-dom';
import { AgentPipeline } from '../../components/AgentPipeline';
import { EventLog } from '../../components/EventLog';
import { Card, ConfidenceBar, Empty, HypothesisStatus, OutcomeBadge, SimulatedNotice } from '../../components/ui';
import type { LiveInvestigation } from '../../hooks';

export default function Workspace({ live }: { live: LiveInvestigation }) {
  const inv = live.investigation!;
  const report = inv.investigation_report;
  const target = report?.target_failure;
  const belief = inv.summary?.belief as { unexplained?: number } | undefined;
  const usage = inv.usage;
  const budget = inv.budget;

  return (
    <div className="stack">
      {inv.simulated && <SimulatedNotice />}
      {inv.provider_note && <div className="alert yellow small">{inv.provider_note}</div>}
      {inv.error && <div className="alert red small">{inv.error}</div>}

      <AgentPipeline investigation={inv} events={live.events} />

      <div className="grid grid-sidebar">
        <div className="stack">
          <Card title="Observed failure">
            {!target ? (
              <Empty>{inv.status === 'completed' ? 'No failing test was observed.' : 'Running the baseline test suite in the sandbox…'}</Empty>
            ) : (
              <div className="stack-sm">
                <div className="row wrap">
                  <code>{target.test_name}</code>
                  <span className="faint small">{target.file}</span>
                  <span className="spacer" />
                  {report?.reproduction_confirmed != null && (
                    <span className={`badge ${report.reproduction_confirmed ? 'green' : 'yellow'}`}>
                      {report.reproduction_confirmed ? 'reproduced in isolation' : 'not reproducible in isolation'}
                    </span>
                  )}
                </div>
                <pre className="code wrap">
                  {target.error_name}: {target.error}
                </pre>
                {target.stack_frames.length > 0 && (
                  <div className="mono faint small">{target.stack_frames.slice(0, 4).map((f) => <div key={f}>{f}</div>)}</div>
                )}
                {inv.symptom && (
                  <div className="small">
                    <span className="label">Reported symptom</span> <span className="muted">{inv.symptom}</span>
                  </div>
                )}
              </div>
            )}
          </Card>

          <Card
            title="Competing hypotheses"
            actions={belief?.unexplained != null && <span className="faint small">unexplained mass {(belief.unexplained * 100).toFixed(0)}%</span>}
            flush
          >
            {!live.hypotheses.length ? (
              <Empty>{inv.mode === 'baseline' ? 'Baseline A does not generate hypotheses.' : 'No hypotheses yet.'}</Empty>
            ) : (
              <table className="table">
                <tbody>
                  {live.hypotheses.map((h) => (
                    <tr key={h.id}>
                      <td style={{ width: 44 }} className="mono">
                        {h.key}
                      </td>
                      <td>
                        <div style={{ fontWeight: 500 }}>{h.title}</div>
                        <div className="muted small" style={{ marginTop: 2 }}>
                          {h.explanation}
                        </div>
                        {h.suspected_locations.length > 0 && (
                          <div className="row wrap" style={{ marginTop: 6 }}>
                            {h.suspected_locations.map((loc) => (
                              <code key={loc} className="faint">
                                {loc}
                              </code>
                            ))}
                          </div>
                        )}
                        {h.history.length > 0 && (
                          <div className="faint small" style={{ marginTop: 6 }}>
                            {h.history.map((step) => (
                              <span key={step.experiment} style={{ marginRight: 10 }}>
                                {step.experiment}{' '}
                                <span style={{ color: step.matched == null ? undefined : step.matched ? 'var(--green)' : 'var(--red)' }}>
                                  {step.matched == null ? '·' : step.matched ? '✔' : '✘'}
                                </span>{' '}
                                {step.before.toFixed(2)}→{step.after.toFixed(2)}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td style={{ width: 170 }}>
                        <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
                          <HypothesisStatus status={h.status} />
                          <span className="mono small">{(h.confidence * 100).toFixed(0)}%</span>
                        </div>
                        <ConfidenceBar value={h.confidence} status={h.status} />
                        <div className="faint small" style={{ marginTop: 4 }}>
                          prior {(h.prior * 100).toFixed(0)}%
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card
            title="Experiments"
            actions={
              <Link className="btn ghost sm" to="timeline">
                Timeline
              </Link>
            }
            flush
          >
            {!live.experiments.length ? (
              <Empty>No experiments yet.</Empty>
            ) : (
              <table className="table">
                <tbody>
                  {live.experiments.map((e) => (
                    <tr key={e.id}>
                      <td className="mono" style={{ width: 44 }}>
                        {e.key}
                      </td>
                      <td>
                        <div>{e.objective}</div>
                        <div className="faint small">
                          {e.kind}
                          {e.spec.source_edits?.length ? ' · counterfactual intervention' : ''}
                          {e.evaluation?.detail ? ` · ${e.evaluation.detail}` : ''}
                        </div>
                      </td>
                      <td style={{ width: 110 }}>
                        <OutcomeBadge outcome={e.outcome} status={e.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>

        <div className="stack">
          <Card title="Live execution log" actions={<span className="faint small">{live.events.length} events</span>} flush>
            <EventLog events={live.events} />
          </Card>
          <Card title="Budget">
            <dl className="kv">
              <dt>Model calls</dt>
              <dd className="mono">
                {usage.model_calls ?? 0} / {budget.max_model_calls ?? '—'}
              </dd>
              <dt>Experiments</dt>
              <dd className="mono">
                {usage.experiments ?? 0} / {budget.max_experiments ?? '—'}
              </dd>
              <dt>Sandbox runs</dt>
              <dd className="mono">{usage.sandbox_runs ?? 0}</dd>
              <dt>Tokens</dt>
              <dd className="mono">
                {usage.total_tokens ?? 0}
                {usage.tokens_estimated ? ' (estimated)' : ''}
              </dd>
              <dt>Est. cost</dt>
              <dd className="mono">
                ${(usage.estimated_cost_usd ?? 0).toFixed(4)}
                {inv.simulated ? <span className="faint"> hypothetical</span> : null}
              </dd>
              <dt>Elapsed</dt>
              <dd className="mono">
                {usage.elapsed_s ?? 0}s / {budget.time_budget_s ?? '—'}s
              </dd>
            </dl>
          </Card>
          {inv.root_cause && (
            <Card title="Suspected root cause">
              <p>{inv.root_cause}</p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
