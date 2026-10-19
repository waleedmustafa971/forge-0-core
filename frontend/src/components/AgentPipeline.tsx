import type { ForgeEvent, Investigation } from '../api/types';

export const AGENTS = [
  { id: 'orchestrator', letter: 'G', name: 'Orchestrator' },
  { id: 'investigator', letter: 'A', name: 'Investigator' },
  { id: 'hypothesis_generator', letter: 'B', name: 'Hypotheses' },
  { id: 'experiment_designer', letter: 'C', name: 'Designer' },
  { id: 'experiment_executor', letter: 'D', name: 'Executor' },
  { id: 'repair_engineer', letter: 'E', name: 'Repair' },
  { id: 'verifier', letter: 'F', name: 'Verifier' },
] as const;

export const AGENT_NAMES: Record<string, string> = Object.fromEntries(
  AGENTS.map((a) => [a.id, `${a.letter} · ${a.name}`]),
);

export function AgentPipeline({ investigation, events }: { investigation: Investigation; events: ForgeEvent[] }) {
  const seen = new Set(events.map((e) => e.agent));
  const running = investigation.status === 'running' || investigation.status === 'queued';
  const active = running ? (investigation.active_agent ?? 'orchestrator') : null;
  return (
    <div className="pipeline">
      {AGENTS.map((agent) => {
        const state = agent.id === active ? 'active' : seen.has(agent.id) ? 'done' : '';
        const count = events.filter((e) => e.agent === agent.id).length;
        return (
          <div className={`agent ${state}`} key={agent.id}>
            <div className="row">
              <span className="agent-letter">{agent.letter}</span>
              <span className="spacer" />
              {state === 'active' && <span className="dot pulse" style={{ color: 'var(--accent)' }} />}
            </div>
            <div className="agent-name">{agent.name}</div>
            <div className="faint small">{count ? `${count} events` : 'idle'}</div>
          </div>
        );
      })}
    </div>
  );
}
