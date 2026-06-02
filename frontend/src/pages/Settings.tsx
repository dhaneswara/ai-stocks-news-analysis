import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useProviders, useSaveSettings, useSettings } from '../hooks/queries';
import type { ProviderId, Settings as SettingsT, TestResult } from '../types';

export default function Settings() {
  const settingsQuery = useSettings();
  const providers = useProviders();
  const save = useSaveSettings();
  const [form, setForm] = useState<SettingsT | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settingsQuery.data) setForm(structuredClone(settingsQuery.data));
  }, [settingsQuery.data]);

  if (!form) return <p className="muted">Loading settings…</p>;

  const active = form.active_provider;
  const cfg = form.providers[active];
  const update = (next: Partial<SettingsT>) => { setForm({ ...form, ...next }); setSaved(false); };
  const updateCfg = (patch: Partial<typeof cfg>) =>
    update({ providers: { ...form.providers, [active]: { ...cfg, ...patch } } });

  const onSave = () => save.mutate(form, { onSuccess: () => setSaved(true) });
  const onTest = async () => {
    setTest(null);
    // Persist first so the backend tests the current form values.
    await save.mutateAsync(form);
    setTest(await api.testProvider(active));
  };

  return (
    <div className="panel" style={{ maxWidth: 640 }}>
      <h3 style={{ marginTop: 0 }}>Provider settings</h3>

      <div className="field">
        <label>Active provider</label>
        <select value={active} onChange={(e) => update({ active_provider: e.target.value as ProviderId })}>
          {(providers.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>{p.label}{p.configured ? ' ✓' : ''}</option>
          ))}
        </select>
      </div>

      <div className="field">
        <label>Model</label>
        <input value={cfg.model} onChange={(e) => updateCfg({ model: e.target.value })} placeholder="model name" />
      </div>

      {active === 'ollama' ? (
        <div className="field">
          <label>Base URL</label>
          <input value={cfg.base_url} onChange={(e) => updateCfg({ base_url: e.target.value })} placeholder="http://localhost:11434" />
        </div>
      ) : (
        <div className="field">
          <label>API key (leave as **** to keep the saved key)</label>
          <input type="password" value={cfg.api_key} onChange={(e) => updateCfg({ api_key: e.target.value })} placeholder="paste API key" />
        </div>
      )}

      <div className="field">
        <label>Watchlist (comma-separated)</label>
        <input
          value={form.watchlist.join(', ')}
          onChange={(e) => update({ watchlist: e.target.value.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean) })}
        />
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={onSave} disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save'}</button>
        <button className="secondary" onClick={onTest} disabled={save.isPending}>Test connection</button>
        {saved && <span className="muted">Saved.</span>}
        {test && <span className={test.ok ? 'muted' : 'error'}>{test.ok ? '✓ ' : '✗ '}{test.message}</span>}
      </div>
      {save.isError && <p className="error">Save failed: {(save.error as Error).message}</p>}
    </div>
  );
}
