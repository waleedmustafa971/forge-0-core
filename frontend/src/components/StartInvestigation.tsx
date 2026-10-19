import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { Repository, ScanResult } from '../api/types';
import { Spinner } from './ui';

export function StartInvestigation({
  repositories,
  initialRepoId,
  onClose,
}: {
  repositories: Repository[];
  initialRepoId?: string;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [repoId, setRepoId] = useState(initialRepoId ?? repositories[0]?.id ?? '');
  const repo = repositories.find((r) => r.id === repoId);
  const [scan, setScan] = useState<ScanResult | null>(repo?.last_scan ?? null);
  const [scanning, setScanning] = useState(false);
  const [target, setTarget] = useState('');
  const [symptom, setSymptom] = useState('');
  const [mode, setMode] = useState<'forge' | 'baseline'>('forge');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const r = repositories.find((x) => x.id === repoId);
    setScan(r?.last_scan ?? null);
    setTarget('');
  }, [repoId, repositories]);

  const failing = scan?.tests.filter((t) => t.status === 'failed') ?? [];

  const runScan = async () => {
    setScanning(true);
    setError(null);
    try {
      setScan(await api.scan(repoId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setScanning(false);
    }
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const inv = await api.createInvestigation({
        repository_id: repoId,
        target_test: target || null,
        symptom,
        mode,
      });
      navigate(`/investigations/${inv.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="card modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <header className="card-header">
          <h2>New investigation</h2>
          <button className="btn ghost sm" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="card-body stack">
          <label className="field">
            <span>Repository</span>
            <select className="select" value={repoId} onChange={(e) => setRepoId(e.target.value)}>
              {repositories.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>

          <div className="field">
            <span>Observed failure</span>
            <div className="row">
              <select className="select" value={target} onChange={(e) => setTarget(e.target.value)} disabled={!scan}>
                <option value="">{scan ? 'First failing test' : 'Scan the test suite to choose a failing test'}</option>
                {failing.map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.name}
                  </option>
                ))}
              </select>
              <button className="btn" onClick={runScan} disabled={scanning || !repoId}>
                {scanning ? <Spinner /> : null}
                {scanning ? 'Running in sandbox…' : scan ? 'Re-scan' : 'Scan tests'}
              </button>
            </div>
            {scan && (
              <span className="hint">
                Sandbox run: {scan.passed} passed, {scan.failed} failed of {scan.total} in {scan.duration_ms} ms
              </span>
            )}
          </div>

          <label className="field">
            <span>Symptom (optional)</span>
            <textarea
              className="textarea"
              value={symptom}
              placeholder="e.g. Customers report being charged twice after checkout timeouts"
              onChange={(e) => setSymptom(e.target.value)}
            />
          </label>

          <div className="field">
            <span>Method</span>
            <div className="grid grid-2">
              <button
                className={`card stat ${mode === 'forge' ? 'selected' : ''}`}
                style={{ textAlign: 'left', cursor: 'pointer', borderColor: mode === 'forge' ? 'var(--accent)' : undefined }}
                onClick={() => setMode('forge')}
              >
                <strong>System B · FORGE-0</strong>
                <div className="muted small">Competing hypotheses, discriminating experiments, verified repair.</div>
              </button>
              <button
                className="card stat"
                style={{ textAlign: 'left', cursor: 'pointer', borderColor: mode === 'baseline' ? 'var(--accent)' : undefined }}
                onClick={() => setMode('baseline')}
              >
                <strong>Baseline A · one-shot</strong>
                <div className="muted small">Direct repair from the failure context; verified afterwards only to measure it.</div>
              </button>
            </div>
          </div>

          {error && <div className="alert red">{error}</div>}
          <div className="row">
            <span className="spacer" />
            <button className="btn" onClick={onClose}>
              Cancel
            </button>
            <button className="btn primary" onClick={submit} disabled={submitting || !repoId}>
              {submitting ? 'Starting…' : 'Start investigation'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
