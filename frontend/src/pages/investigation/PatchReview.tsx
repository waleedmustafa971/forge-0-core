import { useState } from 'react';
import { api } from '../../api/client';
import type { Patch } from '../../api/types';
import { DiffViewer } from '../../components/DiffViewer';
import { IconDownload } from '../../components/icons';
import { Card, Empty, PatchStatus, Spinner } from '../../components/ui';
import type { LiveInvestigation } from '../../hooks';

function VerificationTable({ patch }: { patch: Patch }) {
  const v = patch.verification;
  if (!v) return <span className="faint small">Not verified.</span>;
  const changed = (v.deltas ?? []).filter((d) => d.baseline !== d.patched);
  return (
    <div className="stack-sm">
      <div className={`alert ${v.verdict === 'verified' ? 'green' : 'red'} small`}>
        <strong>{v.verdict.toUpperCase()}</strong>
        <span>{v.reasons.join(' · ')}</span>
      </div>
      <div className="grid grid-3">
        <div className="card stat">
          <div className="label">Target test</div>
          <div className="row" style={{ marginTop: 6 }}>
            <span className="badge red">{v.target_baseline ?? '—'}</span>→
            <span className={`badge ${v.target_patched === 'passed' ? 'green' : 'red'}`}>{v.target_patched ?? '—'}</span>
          </div>
          <div className="stat-sub">isolated re-runs: {v.target_repeat_runs?.join(', ') || '—'}</div>
        </div>
        <div className="card stat">
          <div className="label">Baseline suite</div>
          <div className="stat-value" style={{ fontSize: 18 }}>
            {v.baseline_summary?.passed ?? 0} / {v.baseline_summary?.total ?? 0}
          </div>
          <div className="stat-sub">passing before the patch</div>
        </div>
        <div className="card stat">
          <div className="label">Patched suite</div>
          <div className="stat-value" style={{ fontSize: 18 }}>
            {v.patched_summary?.passed ?? 0} / {v.patched_summary?.total ?? 0}
          </div>
          <div className="stat-sub">
            {v.fixed?.length ?? 0} fixed · <span style={{ color: v.regressions?.length ? 'var(--red)' : undefined }}>{v.regressions?.length ?? 0} regressions</span>
          </div>
        </div>
      </div>
      {changed.length > 0 && (
        <table className="table" style={{ border: '1px solid var(--border)' }}>
          <thead>
            <tr>
              <th>Test whose result changed</th>
              <th>Original</th>
              <th>Patched</th>
            </tr>
          </thead>
          <tbody>
            {changed.map((d) => (
              <tr key={d.name}>
                <td className="small">{d.name}</td>
                <td>
                  <span className={`badge ${d.baseline === 'passed' ? 'green' : 'red'}`}>{d.baseline ?? 'missing'}</span>
                </td>
                <td>
                  <span className={`badge ${d.patched === 'passed' ? 'green' : 'red'}`}>{d.patched ?? 'missing'}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {v.still_failing?.length > 0 && (
        <div className="faint small">Unrelated failures unchanged by this patch: {v.still_failing.join('; ')}</div>
      )}
      {v.reverification && (
        <div className={`alert ${v.reverification.verdict === 'verified' ? 'green' : 'red'} small`}>
          <strong>Re-verification: {v.reverification.verdict}</strong>
          <span>{v.reverification.reasons.join(' · ')}</span>
        </div>
      )}
    </div>
  );
}

function PatchCard({ patch, investigationId, onChange }: { patch: Patch; investigationId: string; onChange: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card
      title={
        <div className="row wrap">
          <span className="mono">{patch.key}</span>
          <h2>{patch.summary}</h2>
          <PatchStatus status={patch.status} />
          {patch.review_status !== 'pending' && (
            <span className={`badge ${patch.review_status === 'approved' ? 'green' : 'red'}`}>review: {patch.review_status}</span>
          )}
        </div>
      }
      actions={
        patch.diff && (
          <a className="btn sm" href={`/api/investigations/${investigationId}/patches/${patch.id}/diff`}>
            <IconDownload width={14} /> .patch
          </a>
        )
      }
    >
      <div className="stack">
        <div>
          <div className="label">Rationale{patch.hypothesis_key ? ` · addresses ${patch.hypothesis_key}` : ''}</div>
          <p style={{ marginTop: 4 }}>{patch.rationale}</p>
        </div>
        {patch.files_changed.length > 0 && (
          <div className="row wrap small">
            {patch.files_changed.map((f) => (
              <span key={f.path} className="badge outline mono">
                {f.path} <span style={{ color: 'var(--green)' }}>+{f.added}</span>
                <span style={{ color: 'var(--red)' }}>−{f.removed}</span>
                {f.created ? ' new' : ''}
              </span>
            ))}
          </div>
        )}
        {patch.diff ? <DiffViewer diff={patch.diff} /> : <Empty>No diff produced.</Empty>}
        <div>
          <div className="label" style={{ marginBottom: 6 }}>Independent verification</div>
          <VerificationTable patch={patch} />
        </div>
        {error && <div className="alert red small">{error}</div>}
        {patch.edits.length > 0 && (
          <div className="row">
            <button className="btn sm" disabled={!!busy} onClick={() => run('verify', () => api.reverify(investigationId, patch.id))}>
              {busy === 'verify' && <Spinner />} Re-run verification
            </button>
            <span className="spacer" />
            <span className="faint small">FORGE-0 never applies patches to your repository.</span>
            <button
              className="btn sm"
              disabled={!!busy || patch.status !== 'verified'}
              title={patch.status !== 'verified' ? 'Only verified patches can be approved' : undefined}
              onClick={() => run('approve', () => api.reviewPatch(investigationId, patch.id, 'approved'))}
            >
              Approve
            </button>
            <button className="btn sm danger" disabled={!!busy} onClick={() => run('reject', () => api.reviewPatch(investigationId, patch.id, 'rejected'))}>
              Reject
            </button>
          </div>
        )}
      </div>
    </Card>
  );
}

export default function PatchReview({ live }: { live: LiveInvestigation }) {
  if (!live.patches.length) return <Empty>No candidate patches yet.</Empty>;
  const ordered = [...live.patches].sort((a, b) => Number(b.status === 'verified') - Number(a.status === 'verified') || b.attempt - a.attempt);
  return (
    <div className="stack">
      {ordered.map((p) => (
        <PatchCard key={p.id} patch={p} investigationId={live.investigation!.id} onChange={() => void live.refresh()} />
      ))}
    </div>
  );
}
