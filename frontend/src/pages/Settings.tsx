import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { RuntimeConfig } from '../api/types';
import { Card, Spinner } from '../components/ui';
import { useAsync } from '../hooks';

const PROVIDERS: { id: RuntimeConfig['ai_provider']; name: string; text: string }[] = [
  { id: 'mock', name: 'Mock (scripted)', text: 'Deterministic fixtures. No network, no credentials, clearly labelled as simulated.' },
  { id: 'meta', name: 'Meta Model API', text: 'Muse Spark via api.meta.ai. Requires META_API_KEY in the backend environment.' },
  { id: 'openai', name: 'OpenAI-compatible', text: 'Any /v1/chat/completions endpoint (vLLM, Ollama, gateways).' },
];

export default function Settings() {
  const settings = useAsync(() => api.settings(), []);
  const [form, setForm] = useState<RuntimeConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [check, setCheck] = useState<Record<string, unknown> | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    if (settings.data) setForm(settings.data.runtime);
  }, [settings.data]);

  if (!settings.data || !form) return settings.error ? <div className="alert red">{settings.error}</div> : <Spinner />;
  const s = settings.data;
  const set = <K extends keyof RuntimeConfig>(key: K, value: RuntimeConfig[K]) => setForm({ ...form, [key]: value });

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const updated = await api.updateSettings(form);
      setForm(updated);
      setMessage('Saved. New investigations use these settings.');
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const runCheck = async (deep: boolean) => {
    setChecking(true);
    setCheck(null);
    try {
      setCheck(await api.checkProvider(form.ai_provider, deep));
    } catch (err) {
      setCheck({ ok: false, detail: err instanceof Error ? err.message : String(err) });
    } finally {
      setChecking(false);
    }
  };

  const keyMissing = form.ai_provider === 'meta' && !s.secrets.meta_api_key_configured;

  return (
    <div className="stack fade-in" style={{ maxWidth: 980 }}>
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Provider selection and investigation budgets. API keys are read from the backend environment only and are never sent to the browser.</p>
        </div>
      </div>

      <Card title="AI provider">
        <div className="stack">
          <div className="grid grid-3">
            {PROVIDERS.map((p) => (
              <button
                key={p.id}
                className="card stat"
                style={{ textAlign: 'left', cursor: 'pointer', borderColor: form.ai_provider === p.id ? 'var(--accent)' : undefined }}
                onClick={() => set('ai_provider', p.id)}
              >
                <strong>{p.name}</strong>
                <div className="muted small" style={{ marginTop: 4 }}>
                  {p.text}
                </div>
              </button>
            ))}
          </div>
          {keyMissing && (
            <div className="alert amber small">
              META_API_KEY is not configured. Investigations will fall back to the mock provider and be labelled as simulated
              until the key is added to the backend environment and the backend is restarted.
            </div>
          )}
          <div className="grid grid-2">
            <label className="field">
              <span>Meta model</span>
              <input className="input mono" value={form.meta_model} onChange={(e) => set('meta_model', e.target.value)} />
              <span className="hint">Endpoint {s.endpoints.meta_api_base_url} · structured output {s.meta.structured_output}</span>
            </label>
            <label className="field">
              <span>OpenAI-compatible model</span>
              <input className="input mono" value={form.openai_compat_model} onChange={(e) => set('openai_compat_model', e.target.value)} />
              <span className="hint">Endpoint {s.endpoints.openai_compat_base_url}</span>
            </label>
            <label className="field">
              <span>Temperature</span>
              <input
                className="input"
                type="number"
                step="0.1"
                min={0}
                max={2}
                value={form.temperature}
                onChange={(e) => set('temperature', Number(e.target.value))}
              />
            </label>
            <label className="field">
              <span>Max completion tokens</span>
              <input className="input" type="number" min={256} value={form.max_tokens} onChange={(e) => set('max_tokens', Number(e.target.value))} />
            </label>
          </div>
          <div className="row wrap small">
            <span className={`badge ${s.secrets.meta_api_key_configured ? 'green' : 'outline'}`}>
              META_API_KEY {s.secrets.meta_api_key_configured ? 'configured' : 'not set'}
            </span>
            <span className={`badge ${s.secrets.openai_compat_api_key_configured ? 'green' : 'outline'}`}>
              OPENAI_COMPAT_API_KEY {s.secrets.openai_compat_api_key_configured ? 'configured' : 'not set'}
            </span>
            <span className="faint">
              Cost estimates use ${s.pricing.input_per_m}/M input and ${s.pricing.output_per_m}/M output tokens.
            </span>
          </div>
          <div className="row">
            <button className="btn" onClick={() => runCheck(false)} disabled={checking}>
              {checking && <Spinner />} Check connectivity
            </button>
            <button className="btn" onClick={() => runCheck(true)} disabled={checking || form.ai_provider === 'mock'}>
              Test completion (uses tokens)
            </button>
          </div>
          {check && (
            <div className={`alert ${check.ok ? 'green' : 'red'} small`} style={{ display: 'block' }}>
              <strong>{check.ok ? 'Reachable' : 'Not available'}</strong>
              <pre className="code wrap" style={{ marginTop: 8, background: 'transparent', border: 'none', padding: 0 }}>
                {JSON.stringify(check, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </Card>

      <Card title="Investigation budgets">
        <div className="grid grid-3">
          {(
            [
              ['max_model_calls', 'Model calls'],
              ['max_experiments', 'Experiments'],
              ['max_experiment_rounds', 'Experiment rounds'],
              ['max_repair_attempts', 'Repair attempts'],
              ['time_budget_s', 'Time budget (s)'],
            ] as const
          ).map(([key, label]) => (
            <label className="field" key={key}>
              <span>{label}</span>
              <input className="input" type="number" min={1} value={form[key]} onChange={(e) => set(key, Number(e.target.value))} />
            </label>
          ))}
        </div>
      </Card>

      <div className="row">
        <button className="btn primary" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save settings'}
        </button>
        <button
          className="btn ghost"
          onClick={async () => {
            setForm(await api.resetSettings());
            setMessage('Reset to environment defaults.');
          }}
        >
          Reset to environment defaults
        </button>
        {message && <span className="muted small">{message}</span>}
      </div>
    </div>
  );
}
