import { useCallback, useEffect, useRef, useState } from 'react';
import { api, eventStreamUrl } from './api/client';
import type { Experiment, ForgeEvent, Hypothesis, InvestigationDetail, Patch } from './api/types';

export function useAsync<T>(load: () => Promise<T>, deps: unknown[], intervalMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);
  loadRef.current = load;

  const refresh = useCallback(async () => {
    try {
      const value = await loadRef.current();
      setData(value);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void refresh();
    if (!intervalMs) return;
    const timer = window.setInterval(() => void refresh(), intervalMs);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, refresh, setData };
}

export interface LiveInvestigation {
  investigation: InvestigationDetail | null;
  events: ForgeEvent[];
  hypotheses: Hypothesis[];
  experiments: Experiment[];
  patches: Patch[];
  error: string | null;
  connected: boolean;
  refresh: () => Promise<void>;
}

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

/** Subscribes to the investigation's SSE stream and re-fetches derived state as events arrive. */
export function useLiveInvestigation(id: string): LiveInvestigation {
  const [investigation, setInvestigation] = useState<InvestigationDetail | null>(null);
  const [events, setEvents] = useState<ForgeEvent[]>([]);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [patches, setPatches] = useState<Patch[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const pending = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [inv, hyps, exps, pats] = await Promise.all([
        api.investigation(id),
        api.hypotheses(id),
        api.experiments(id),
        api.patches(id),
      ]);
      setInvestigation(inv);
      setHypotheses(hyps);
      setExperiments(exps);
      setPatches(pats);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [id]);

  const scheduleRefresh = useCallback(() => {
    if (pending.current !== null) return;
    pending.current = window.setTimeout(() => {
      pending.current = null;
      void refresh();
    }, 400);
  }, [refresh]);

  useEffect(() => {
    setEvents([]);
    void refresh();
    const source = new EventSource(eventStreamUrl(id));
    source.onopen = () => setConnected(true);
    source.addEventListener('forge', (message) => {
      const event = JSON.parse((message as MessageEvent).data) as ForgeEvent;
      setEvents((prev) => (prev.some((e) => e.id === event.id) ? prev : [...prev, event]));
      scheduleRefresh();
    });
    source.addEventListener('end', () => {
      source.close();
      setConnected(false);
      void refresh();
    });
    source.onerror = () => setConnected(false);
    return () => {
      source.close();
      if (pending.current !== null) window.clearTimeout(pending.current);
      pending.current = null;
    };
  }, [id, refresh, scheduleRefresh]);

  // Safety net: poll while running in case the stream is interrupted by a proxy.
  useEffect(() => {
    if (!investigation || TERMINAL.has(investigation.status)) return;
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [investigation, refresh]);

  return { investigation, events, hypotheses, experiments, patches, error, connected, refresh };
}
