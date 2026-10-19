import { duration } from '../format';
import { NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { ProviderBadge, Spinner, StatusBadge, VerdictBadge } from '../components/ui';
import { useLiveInvestigation } from '../hooks';
import PatchReview from './investigation/PatchReview';
import Report from './investigation/Report';
import Timeline from './investigation/Timeline';
import Workspace from './investigation/Workspace';

export default function InvestigationPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const live = useLiveInvestigation(id);
  const inv = live.investigation;

  if (!inv) {
    return live.error ? <div className="alert red">{live.error}</div> : <Spinner />;
  }
  const running = ['running', 'queued', 'cancelling'].includes(inv.status);

  return (
    <div className="fade-in">
      <div className="page-header">
        <div style={{ minWidth: 0 }}>
          <div className="row wrap" style={{ marginBottom: 6 }}>
            <StatusBadge status={inv.status} />
            <VerdictBadge verdict={inv.verdict} />
            <span className="badge outline">{inv.mode === 'forge' ? 'System B · hypothesis-driven' : 'Baseline A · one-shot'}</span>
            <ProviderBadge provider={inv.provider} model={inv.model} simulated={inv.simulated} />
            {live.connected && running && <span className="badge blue">live</span>}
          </div>
          <h1>{inv.title}</h1>
          <p>
            {inv.repository_name} · {running ? inv.phase : `finished in ${duration(inv.started_at, inv.finished_at)}`}
          </p>
        </div>
        <div className="row">
          {running ? (
            <button className="btn danger" onClick={() => void api.cancelInvestigation(id).then(live.refresh)}>
              Cancel
            </button>
          ) : (
            <button
              className="btn ghost"
              onClick={async () => {
                await api.deleteInvestigation(id);
                navigate('/investigations');
              }}
            >
              Delete
            </button>
          )}
        </div>
      </div>

      <nav className="tabs">
        <NavLink end to={`/investigations/${id}`} className="tab">
          Workspace
        </NavLink>
        <NavLink to={`/investigations/${id}/timeline`} className="tab">
          Experiment timeline · {live.experiments.length}
        </NavLink>
        <NavLink to={`/investigations/${id}/patches`} className="tab">
          Patch review · {live.patches.length}
        </NavLink>
        <NavLink to={`/investigations/${id}/report`} className="tab">
          Evidence report
        </NavLink>
      </nav>

      <Routes>
        <Route index element={<Workspace live={live} />} />
        <Route path="timeline" element={<Timeline live={live} />} />
        <Route path="patches" element={<PatchReview live={live} />} />
        <Route path="report" element={<Report id={id} status={inv.status} />} />
      </Routes>
    </div>
  );
}
