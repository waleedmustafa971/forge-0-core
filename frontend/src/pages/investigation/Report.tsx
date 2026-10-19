import { formatTime } from '../../format';
import { useState } from 'react';
import { api } from '../../api/client';
import { DiffViewer } from '../../components/DiffViewer';
import { Card, Empty, HypothesisStatus, Spinner, VerdictBadge } from '../../components/ui';
import { useAsync } from '../../hooks';

export default function Report({ id, status }: { id: string; status: string }) {
  const report = useAsync(() => api.report(id), [id, status]);
  const [copied, setCopied] = useState(false);
  const r = report.data;
  if (!r) return report.error ? <div className="alert red">{report.error}</div> : <Spinner />;

  const verifiedPatch = r.patches.find((p) => p.key === r.proposed_fix);
  const downloadMarkdown = async () => {
    const md = await api.reportMarkdown(id);
    const url = URL.createObjectURL(new Blob([md], { type: 'text/markdown' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `forge0-report-${id.slice(0, 8)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };
  const copyMarkdown = async () => {
    await navigator.clipboard.writeText(await api.reportMarkdown(id));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="stack">
      <div className="row">
        <VerdictBadge verdict={r.investigation.verdict} />
        <span className="muted">{r.investigation.verdict_text}</span>
        <span className="spacer" />
        <button className="btn sm" onClick={copyMarkdown}>
          {copied ? 'Copied' : 'Copy Markdown'}
        </button>
        <button className="btn sm" onClick={downloadMarkdown}>
          Download .md
        </button>
      </div>
      {r.provider.disclaimer && <div className="alert amber small">{r.provider.disclaimer}</div>}

      <div className="grid grid-2">
        <Card title="Suspected root cause">
          {r.root_cause ? <p>{r.root_cause}</p> : <Empty>Not established.</Empty>}
        </Card>
        <Card title="Observed failure">
          {r.target_failure ? (
            <div className="stack-sm">
              <code>{r.target_failure.test_name}</code>
              <pre className="code wrap">{r.target_failure.error}</pre>
              <span className="small muted">Reproduced in isolation: {String(r.reproduced)}</span>
            </div>
          ) : (
            <Empty>None.</Empty>
          )}
        </Card>
      </div>

      <Card title="Hypotheses and how the evidence ranked them" flush>
        <table className="table">
          <thead>
            <tr>
              <th>Key</th>
              <th>Hypothesis</th>
              <th>Prior</th>
              <th>Final</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {r.hypotheses.map((h) => (
              <tr key={h.key}>
                <td className="mono">{h.key}</td>
                <td>
                  <div>{h.title}</div>
                  <div className="faint small">
                    {h.history.map((s) => `${s.experiment}: ${s.reason ?? 'no prediction'}`).join(' · ')}
                  </div>
                </td>
                <td className="mono">{(h.prior * 100).toFixed(0)}%</td>
                <td className="mono">{(h.confidence * 100).toFixed(0)}%</td>
                <td>
                  <HypothesisStatus status={h.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="Supporting evidence (executed experiments)" flush>
        {!r.experiments.length ? (
          <Empty>No experiments.</Empty>
        ) : (
          <table className="table">
            <tbody>
              {r.experiments.map((e) => (
                <tr key={e.key}>
                  <td className="mono" style={{ width: 44 }}>
                    {e.key}
                  </td>
                  <td>
                    <div>{e.objective}</div>
                    <div className="faint small">
                      {e.kind}
                      {e.intervention ? ' · counterfactual' : ''} · {e.evaluation?.detail}
                    </div>
                    {e.evaluation?.predictions?.map((p) => (
                      <div key={p.hypothesis} className="small" style={{ color: p.matched ? 'var(--green)' : 'var(--red)' }}>
                        {p.matched ? '✔' : '✘'} {p.hypothesis}: {p.reason}
                      </div>
                    ))}
                  </td>
                  <td className="mono small faint" style={{ width: 90 }}>
                    {e.execution.duration_ms != null ? `${e.execution.duration_ms} ms` : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Proposed fix">
        {verifiedPatch ? (
          <div className="stack-sm">
            <strong>
              {verifiedPatch.key}: {verifiedPatch.summary}
            </strong>
            <p className="muted">{verifiedPatch.rationale}</p>
            <DiffViewer diff={verifiedPatch.diff} />
            <div className="alert green small">{verifiedPatch.verification.reasons?.join(' · ')}</div>
          </div>
        ) : (
          <Empty>No patch passed independent verification.</Empty>
        )}
        {r.patches.filter((p) => p.key !== r.proposed_fix).length > 0 && (
          <div className="stack-sm" style={{ marginTop: 14 }}>
            <div className="label">Rejected candidates</div>
            {r.patches
              .filter((p) => p.key !== r.proposed_fix)
              .map((p) => (
                <div key={p.key} className="small">
                  <span className="mono">{p.key}</span> {p.summary} — <span style={{ color: 'var(--red)' }}>{p.verification.reasons?.join('; ') ?? p.status}</span>
                </div>
              ))}
          </div>
        )}
      </Card>

      <div className="grid grid-2">
        <Card title="Evidence timeline" flush>
          <div className="log">
            {r.decisions.map((d, i) => (
              <div className={`log-row t-${d.type}`} key={i}>
                <span className="ts">{formatTime(d.ts)}</span>
                <span className="msg">
                  <span className="agent-tag">{d.type.replace(/_/g, ' ')}</span>
                  {d.message}
                </span>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Usage">
          <dl className="kv">
            <dt>Provider</dt>
            <dd>
              {r.provider.name} / {r.provider.model} {r.provider.simulated ? '(simulated)' : ''}
            </dd>
            <dt>Model calls</dt>
            <dd className="mono">{r.model_calls}</dd>
            <dt>Experiments</dt>
            <dd className="mono">{r.usage?.experiments ?? 0}</dd>
            <dt>Sandbox runs</dt>
            <dd className="mono">{r.usage?.sandbox_runs ?? 0}</dd>
            <dt>Tokens</dt>
            <dd className="mono">
              {r.usage?.total_tokens ?? 0} {r.usage?.tokens_estimated ? '(estimated)' : ''}
            </dd>
            <dt>Est. cost</dt>
            <dd className="mono">${(r.usage?.estimated_cost_usd ?? 0).toFixed(4)}</dd>
            <dt>Elapsed</dt>
            <dd className="mono">{r.usage?.elapsed_s ?? 0} s</dd>
          </dl>
        </Card>
      </div>
    </div>
  );
}
