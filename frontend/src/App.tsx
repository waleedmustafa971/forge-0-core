import { useState } from 'react';
import { NavLink, Route, Routes } from 'react-router-dom';
import { api } from './api/client';
import { IconChart, IconDashboard, IconFlask, IconRepo, IconSettings } from './components/icons';
import { ProviderBadge } from './components/ui';
import { useAsync } from './hooks';
import Benchmarks from './pages/Benchmarks';
import Dashboard from './pages/Dashboard';
import InvestigationPage from './pages/Investigation';
import Investigations from './pages/Investigations';
import Repositories from './pages/Repositories';
import Settings from './pages/Settings';

function HealthDot({ ok, label }: { ok: boolean | undefined; label: string }) {
  const color = ok === undefined ? 'var(--text-faint)' : ok ? 'var(--green)' : 'var(--red)';
  return (
    <div className="row">
      <span className="dot" style={{ color }} />
      <span>{label}</span>
    </div>
  );
}

export default function App() {
  const health = useAsync(() => api.health(), [], 15000);
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? 'dark');
  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem('forge0-theme', next);
    } catch {
      // storage unavailable
    }
    setTheme(next);
  };
  const h = health.data;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">F</div>
          <div>
            <div className="brand-name">FORGE-0</div>
            <div className="brand-sub">evidence-driven debugging</div>
          </div>
        </div>
        <div className="nav-section">Workspace</div>
        <NavLink to="/" end className="nav-link">
          <IconDashboard /> Dashboard
        </NavLink>
        <NavLink to="/repositories" className="nav-link">
          <IconRepo /> Repositories
        </NavLink>
        <NavLink to="/investigations" className="nav-link">
          <IconFlask /> Investigations
        </NavLink>
        <NavLink to="/benchmarks" className="nav-link">
          <IconChart /> Evaluation
        </NavLink>
        <div className="nav-section">System</div>
        <NavLink to="/settings" className="nav-link">
          <IconSettings /> Settings
        </NavLink>
        <div className="sidebar-footer">
          <HealthDot ok={h?.database.ok} label={`Database${h ? ` · ${h.database.dialect}` : ''}`} />
          <HealthDot ok={h?.sandbox.ok} label={`Sandbox${h?.sandbox.server_version ? ` · docker ${h.sandbox.server_version}` : ''}`} />
          <HealthDot ok={health.error ? false : h ? true : undefined} label={`API${h ? ` · v${h.version}` : ''}`} />
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="row small muted">
            {health.error ? <span className="badge red">backend unreachable</span> : null}
            {h?.provider.fallback_reason && <span className="badge yellow">{h.provider.fallback_reason}</span>}
          </div>
          <div className="row">
            {h && <ProviderBadge provider={h.provider.active} model={h.provider.model} simulated={h.provider.simulated} />}
            <button className="btn ghost sm" onClick={toggleTheme} aria-label="Toggle theme">
              {theme === 'dark' ? 'Light' : 'Dark'}
            </button>
          </div>
        </header>
        <main className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/repositories" element={<Repositories />} />
            <Route path="/repositories/:repoId" element={<Repositories />} />
            <Route path="/investigations" element={<Investigations />} />
            <Route path="/investigations/:id/*" element={<InvestigationPage />} />
            <Route path="/benchmarks" element={<Benchmarks />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<div className="empty">Page not found</div>} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
