import { formatDate, duration } from '../format';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { StartInvestigation } from '../components/StartInvestigation';
import { Card, Empty, ProviderBadge, StatusBadge, VerdictBadge } from '../components/ui';
import { useAsync } from '../hooks';

export default function Investigations() {
  const navigate = useNavigate();
  const [status, setStatus] = useState('');
  const list = useAsync(() => api.investigations({ status }), [status], 4000);
  const repos = useAsync(() => api.repositories(), []);
  const [starting, setStarting] = useState(false);

  return (
    <div className="stack fade-in">
      <div className="page-header">
        <div>
          <h1>Investigations</h1>
          <p>Every investigation keeps its full audit trail: hypotheses, experiments, evidence, patches and decisions.</p>
        </div>
        <div className="row">
          <select className="select" style={{ width: 160 }} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {['running', 'queued', 'completed', 'failed', 'cancelled'].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <button className="btn primary" onClick={() => setStarting(true)} disabled={!repos.data?.length}>
            New investigation
          </button>
        </div>
      </div>
      <Card flush>
        {!list.data?.length ? (
          <Empty>{list.loading ? 'Loading…' : 'No investigations match.'}</Empty>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Investigation</th>
                <th>Mode</th>
                <th>Status</th>
                <th>Verdict</th>
                <th>Experiments</th>
                <th>Tokens</th>
                <th>Duration</th>
                <th>Provider</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((inv) => (
                <tr className="clickable" key={inv.id} onClick={() => navigate(`/investigations/${inv.id}`)}>
                  <td style={{ maxWidth: 380 }}>
                    <div>{inv.title}</div>
                    {inv.error && <div className="small" style={{ color: 'var(--red)' }}>{inv.error.slice(0, 120)}</div>}
                  </td>
                  <td className="small muted">{inv.mode === 'forge' ? 'System B' : 'Baseline A'}</td>
                  <td>
                    <StatusBadge status={inv.status} />
                  </td>
                  <td>
                    <VerdictBadge verdict={inv.verdict} />
                  </td>
                  <td className="mono small">{inv.usage.experiments ?? 0}</td>
                  <td className="mono small">
                    {inv.usage.total_tokens ?? 0}
                    {inv.usage.tokens_estimated ? ' est.' : ''}
                  </td>
                  <td className="mono small">{duration(inv.started_at, inv.finished_at)}</td>
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
      {starting && repos.data && <StartInvestigation repositories={repos.data} onClose={() => setStarting(false)} />}
    </div>
  );
}
