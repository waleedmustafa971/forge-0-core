import type { ReactNode } from 'react';
import type { Experiment, Hypothesis, InvestigationStatus, Patch, Verdict } from '../api/types';

export function Card({
  title,
  actions,
  children,
  flush = false,
  className = '',
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-header">
          {typeof title === 'string' ? <h2>{title}</h2> : title}
          {actions && <div className="row">{actions}</div>}
        </header>
      )}
      <div className={`card-body ${flush ? 'flush' : ''}`}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className="stat-value" style={tone ? { color: `var(--${tone})` } : undefined}>
        {value}
      </div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Spinner() {
  return <span className="spinner" aria-label="loading" />;
}

const STATUS_TONE: Record<InvestigationStatus, string> = {
  queued: 'outline',
  running: 'amber',
  cancelling: 'yellow',
  completed: 'green',
  failed: 'red',
  cancelled: 'outline',
};

export function StatusBadge({ status }: { status: InvestigationStatus }) {
  const live = status === 'running' || status === 'queued' || status === 'cancelling';
  return (
    <span className={`badge ${STATUS_TONE[status] ?? ''}`}>
      <span className={`dot ${live ? 'pulse' : ''}`} />
      {status}
    </span>
  );
}

const VERDICT: Record<Verdict, [string, string]> = {
  verified_fix: ['green', 'verified fix'],
  no_verified_fix: ['red', 'no verified fix'],
  inconclusive: ['yellow', 'inconclusive'],
  no_failure_observed: ['outline', 'no failure observed'],
};

export function VerdictBadge({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) return <span className="faint small">—</span>;
  const [tone, text] = VERDICT[verdict] ?? ['outline', verdict];
  return <span className={`badge ${tone}`}>{text}</span>;
}

const HYP_TONE: Record<Hypothesis['status'], string> = {
  open: 'outline',
  supported: 'blue',
  weakened: 'yellow',
  refuted: 'red',
  confirmed: 'green',
};

export function HypothesisStatus({ status }: { status: Hypothesis['status'] }) {
  return <span className={`badge ${HYP_TONE[status]}`}>{status}</span>;
}

export function OutcomeBadge({ outcome, status }: { outcome: Experiment['outcome']; status?: Experiment['status'] }) {
  if (status === 'running') {
    return (
      <span className="badge amber">
        <span className="dot pulse" />
        running
      </span>
    );
  }
  if (status === 'invalid') return <span className="badge red">rejected</span>;
  const tone = outcome === 'pass' ? 'green' : outcome === 'fail' ? 'red' : 'yellow';
  return <span className={`badge ${tone}`}>{outcome ?? 'pending'}</span>;
}

export function PatchStatus({ status }: { status: Patch['status'] }) {
  const tone =
    status === 'verified' ? 'green' : status === 'rejected' || status === 'apply_failed' ? 'red' : 'outline';
  return <span className={`badge ${tone}`}>{status.replace('_', ' ')}</span>;
}

export function ConfidenceBar({ value, status }: { value: number; status?: Hypothesis['status'] }) {
  const color =
    status === 'confirmed'
      ? 'var(--green)'
      : status === 'refuted'
        ? 'var(--red)'
        : status === 'weakened'
          ? 'var(--yellow)'
          : 'var(--blue)';
  return (
    <div className="confidence" title={`${(value * 100).toFixed(1)}%`}>
      <div style={{ width: `${Math.max(1.5, value * 100)}%`, background: color }} />
    </div>
  );
}

export function ProviderBadge({ provider, model, simulated }: { provider: string; model?: string; simulated: boolean }) {
  return simulated ? (
    <span className="badge amber" title="Model outputs are scripted fixtures, not real inference">
      MOCK · scripted
    </span>
  ) : (
    <span className="badge violet" title={model}>
      {provider} · {model}
    </span>
  );
}

export function SimulatedNotice() {
  return (
    <div className="alert amber small">
      <strong>Simulated model output.</strong>
      <span>
        Hypotheses, experiment designs and patches in this investigation come from the mock provider's scripted
        fixtures, not from real inference. Every sandbox execution and verification result shown is real.
      </span>
    </div>
  );
}
