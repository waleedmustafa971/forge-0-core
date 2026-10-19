import { formatTime } from '../format';
import { useEffect, useRef } from 'react';
import type { ForgeEvent } from '../api/types';
import { AGENT_NAMES } from './AgentPipeline';


export function EventLog({ events, follow = true }: { events: ForgeEvent[]; follow?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (follow && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [events.length, follow]);
  if (!events.length) return <div className="empty small">Waiting for events…</div>;
  return (
    <div className="log" ref={ref} role="log" aria-live="polite">
      {events.map((event) => (
        <div className={`log-row t-${event.type} fade-in`} key={event.id}>
          <span className="ts">{formatTime(event.ts)}</span>
          <span className="msg">
            <span className="agent-tag" title={event.agent}>
              {AGENT_NAMES[event.agent] ?? event.agent}
            </span>
            {event.message}
          </span>
        </div>
      ))}
    </div>
  );
}
