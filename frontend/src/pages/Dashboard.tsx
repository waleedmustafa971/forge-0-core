import { formatTime, formatDate, duration } from '../format';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { AGENT_NAMES } from '../components/AgentPipeline';
import { StartInvestigation } from '../components/StartInvestigation';
import { Card, Empty, ProviderBadge, Stat, StatusBadge, VerdictBadge } from '../components/ui';
import { useAsync } from '../hooks';

export default function Dashboard() {
  const navigate = useNavigate();
  const stats = useAsync(() => api.dashboard(), [], 4000);
  const investigations = useAsync(() => api.investigations(), [], 4000);
  const repositories = useAsync(() => api.repositories(), []);
  const [starting, setStarting] = useState(false);
  const s = stats.data;
  const invs = investigations.data ?? [];
  const active = invs.filter((i) => ['running', 'queued', 'cancelling'].includes(i.status));

  return (
    <div className="stack fade-in">
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p>Hypothesis-driven investigations with sandboxed experiments and independently verified repairs.</p>
        </div>
        <button className="btn primary" onClick={() => setStarting(true)} disabled={!repositories.data?.length}>
          New investigation
        </button>
      </div>

      {stats.error && <div className="alert red">Backend unreachable: {stats.error}</div>}

      <div className="grid grid-stats">
        <Stat label="Active" value={s?.active ?? '—'} sub="queued or running" tone={s?.active ? 'accent' : undefined} />
        <Stat label="Completed" value={s?.completed ?? '—'} sub={`${s?.failed ?? 0} failed to run`} />
        <Stat label="Verified repairs" value={s?.verified_repairs ?? '—'} sub="passed independent verification" tone="green" />
        <Stat label="Rejected patches" value={s?.patches_rejected ?? '—'} sub="caught by the verifier" tone="red" />
        <Stat
          label="Experiments"
          value={s?.experiments_total ?? '—'}
          sub={`${s?.experiments_failed_to_run ?? 0} errored or timed out`}
        />
      </div>

      <div className="grid grid-sidebar">
        <div className="stack">
          {active.length > 0 && (
            <Card title="Active investigations" flush>
              <table className="table">
                <tbody>
                  {active.map((inv) => (
                    <tr className="clickable" key={inv.id} onClick={() => navigate(`/investigations/${inv.id}`)}>
                      <td>
                        <div>{inv.title}</div>
                        <div className="faint small">{inv.phase}</div>
                      </td>
                      <td>
                        <StatusBadge status={inv.status} />
                      </td>
                      <td className="muted small">{inv.active_agent ? AGENT_NAMES[inv.active_agent] : '—'}</td>
                      <td className="muted small">{duration(inv.started_at, null)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
          <Card
            title="Recent investigations"
            actions={
              <Link to="/investigations" className="btn ghost sm">
                View all
              </Link>
            }
            flush
          >
            {invs.length === 0 ? (
              <Empty>
                No investigations yet. Start one against the bundled demo repository to see the full workflow.
              </Empty>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Investigation</th>
                    <th>Mode</th>
                    <th>Status</th>
                    <th>Verdict</th>
                    <th>Provider</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {invs.slice(0, 10).map((inv) => (
                    <tr className="clickable" key={inv.id} onClick={() => navigate(`/investigations/${inv.id}`)}>
                      <td style={{ maxWidth: 360 }}>{inv.title}</td>
                      <td className="small muted">{inv.mode === 'forge' ? 'System B' : 'Baseline A'}</td>
                      <td>
                        <StatusBadge status={inv.status} />
                      </td>
                      <td>
                        <VerdictBadge verdict={inv.verdict} />
                      </td>
                      <td>
                        <ProviderBadge provider={inv.provider} model={inv.model} simulated={inv.simulated} />
                      </td>
                      <td className="small muted">{formatDate(inv.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>

        <Card title="Recent activity" flush>
          {!s?.recent_activity.length ? (
            <Empty>No activity yet.</Empty>
          ) : (
            <div className="log" style={{ maxHeight: 640 }}>
              {s.recent_activity.map((e) => (
                <Link
                  to={`/investigations/${e.investigation_id}`}
                  key={e.id}
                  className={`log-row t-${e.type}`}
                  style={{ gridTemplateColumns: '64px 1fr' }}
                >
                  <span className="ts">{formatTime(e.ts)}</span>
                  <span className="msg">
                    <span className="faint">{AGENT_NAMES[e.agent] ?? e.agent} · </span>
                    {e.message.length > 160 ? `${e.message.slice(0, 160)}…` : e.message}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </Card>
      </div>

      {starting && repositories.data && (
        <StartInvestigation repositories={repositories.data} onClose={() => setStarting(false)} />
      )}
    </div>
  );
}
