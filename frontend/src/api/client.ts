import type {
  BenchmarkRunSummary,
  Dashboard,
  EvidenceReport,
  Experiment,
  ForgeEvent,
  Health,
  Hypothesis,
  Investigation,
  InvestigationDetail,
  Patch,
  Repository,
  RuntimeConfig,
  ScanResult,
  SettingsResponse,
  Verification,
} from './types';

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch {
      // non-JSON error body
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  const type = response.headers.get('content-type') ?? '';
  return (type.includes('application/json') ? response.json() : response.text()) as Promise<T>;
}

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

export const api = {
  health: () => request<Health>('/system/health'),
  dashboard: () => request<Dashboard>('/dashboard'),

  repositories: () => request<Repository[]>('/repositories'),
  repository: (id: string) => request<Repository>(`/repositories/${id}`),
  importRepository: (body: { source_type: 'local' | 'git'; path?: string; url?: string; ref?: string; name?: string }) =>
    request<Repository>('/repositories', json(body)),
  deleteRepository: (id: string) => request<void>(`/repositories/${id}`, { method: 'DELETE' }),
  tree: (id: string) => request<{ files: { path: string; size: number }[] }>(`/repositories/${id}/tree`),
  file: (id: string, path: string) =>
    request<{ path: string; content: string; size: number; binary: boolean; truncated?: boolean }>(
      `/repositories/${id}/file?path=${encodeURIComponent(path)}`,
    ),
  scan: (id: string) => request<ScanResult>(`/repositories/${id}/scan`, { method: 'POST' }),

  investigations: (params: { status?: string; repository_id?: string } = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return request<Investigation[]>(`/investigations${qs.size ? `?${qs}` : ''}`);
  },
  investigation: (id: string) => request<InvestigationDetail>(`/investigations/${id}`),
  createInvestigation: (body: {
    repository_id: string;
    target_test?: string | null;
    symptom?: string;
    title?: string;
    mode: 'forge' | 'baseline';
  }) => request<Investigation>('/investigations', json(body)),
  cancelInvestigation: (id: string) => request<Investigation>(`/investigations/${id}/cancel`, { method: 'POST' }),
  deleteInvestigation: (id: string) => request<void>(`/investigations/${id}`, { method: 'DELETE' }),
  events: (id: string, after = 0) => request<ForgeEvent[]>(`/investigations/${id}/events?after=${after}`),
  hypotheses: (id: string) => request<Hypothesis[]>(`/investigations/${id}/hypotheses`),
  experiments: (id: string) => request<Experiment[]>(`/investigations/${id}/experiments`),
  patches: (id: string) => request<Patch[]>(`/investigations/${id}/patches`),
  reviewPatch: (id: string, patchId: string, decision: 'approved' | 'rejected' | 'pending', note?: string) =>
    request<Patch>(`/investigations/${id}/patches/${patchId}/review`, json({ decision, note })),
  reverify: (id: string, patchId: string) =>
    request<{ patch_key: string; verification: Verification }>(`/investigations/${id}/verify`, json({ patch_id: patchId })),
  report: (id: string) => request<EvidenceReport>(`/investigations/${id}/report`),
  reportMarkdown: (id: string) => request<string>(`/investigations/${id}/report?format=md`),

  settings: () => request<SettingsResponse>('/settings'),
  updateSettings: (body: Partial<RuntimeConfig>) =>
    request<RuntimeConfig>('/settings', { method: 'PUT', body: JSON.stringify(body) }),
  resetSettings: () => request<RuntimeConfig>('/settings/reset', { method: 'POST' }),
  checkProvider: (provider?: string, deep = false) =>
    request<Record<string, unknown>>('/system/provider/check', json({ provider, deep })),

  benchmarks: () => request<{ runs: BenchmarkRunSummary[] }>('/benchmarks'),
  benchmark: (name: string) => request<Record<string, unknown>>(`/benchmarks/${encodeURIComponent(name)}`),
};

export function eventStreamUrl(id: string, after = 0): string {
  return `/api/investigations/${id}/events/stream?after=${after}`;
}
