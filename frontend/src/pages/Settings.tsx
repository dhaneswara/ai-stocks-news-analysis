import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useListModels, useProviders, useSaveSettings, useSettings } from '../hooks/queries';
import type { AlertConfig, ProviderId, Settings as SettingsT, TestResult, TruthSignalConfig } from '../types';

export default function Settings() {
  const settingsQuery = useSettings();
  const providers = useProviders();
  const save = useSaveSettings();
  const [form, setForm] = useState<SettingsT | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [alertTest, setAlertTest] = useState<TestResult | null>(null);
  const [saved, setSaved] = useState(false);
  const listModels = useListModels();
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [modelsMsg, setModelsMsg] = useState<TestResult | null>(null);

  useEffect(() => {
    if (settingsQuery.data) setForm(structuredClone(settingsQuery.data));
  }, [settingsQuery.data]);

  if (!form) return <p className="muted">Loading settings…</p>;

  const active = form.active_provider;
  const cfg = form.providers[active];
  const fetched = models[active] ?? [];
  const update = (next: Partial<SettingsT>) => { setForm({ ...form, ...next }); setSaved(false); };
  const updateCfg = (patch: Partial<typeof cfg>) =>
    update({ providers: { ...form.providers, [active]: { ...cfg, ...patch } } });
  const updateAlerts = (patch: Partial<AlertConfig>) => update({ alerts: { ...form.alerts, ...patch } });
  const updateTruth = (patch: Partial<TruthSignalConfig>) => update({ truth_signal: { ...form.truth_signal, ...patch } });

  const onSave = () => save.mutate(form, { onSuccess: () => setSaved(true) });
  const onTest = async () => {
    setTest(null);
    await save.mutateAsync(form);
    setTest(await api.testProvider(active));
  };
  const onTestAlert = async () => {
    setAlertTest(null);
    await save.mutateAsync(form);
    setAlertTest(await api.testAlert());
  };
  const onFetchModels = async () => {
    setModelsMsg(null);
    await save.mutateAsync(form);
    listModels.mutate(active, {
      onSuccess: (res) => {
        if (res.error) setModelsMsg({ ok: false, message: res.error });
        else {
          setModels((m) => ({ ...m, [active]: res.models }));
          setModelsMsg({ ok: true, message: `${res.models.length} models` });
        }
      },
      onError: (e) => setModelsMsg({ ok: false, message: (e as Error).message }),
    });
  };

  return (
    <div className="panel settings">
      <h3>Provider settings</h3>

      <div className="field">
        <label>Active provider</label>
        <select value={active} onChange={(e) => update({ active_provider: e.target.value as ProviderId })}>
          {(providers.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>{p.label}{p.configured ? ' ✓' : ''}</option>
          ))}
        </select>
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
        <label>Model</label>
        <div className="model-row">
          <input list="model-options" value={cfg.model} onChange={(e) => updateCfg({ model: e.target.value })} placeholder="model name" />
          <button className="secondary" onClick={onFetchModels} disabled={save.isPending || listModels.isPending}>
            {listModels.isPending ? 'Fetching…' : 'Fetch models'}
          </button>
          {modelsMsg && (
            <span className={`note ${modelsMsg.ok ? 'muted' : 'error'}`}>
              {modelsMsg.ok ? `✓ ${modelsMsg.message}` : `✗ ${modelsMsg.message}`}
            </span>
          )}
        </div>
        <datalist id="model-options">
          {fetched.map((m) => <option key={m} value={m} />)}
        </datalist>
      </div>

      <div className="field">
        <label>Watchlist (comma-separated)</label>
        <input
          value={form.watchlist.join(', ')}
          onChange={(e) => update({ watchlist: e.target.value.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean) })}
        />
      </div>

      <h3>Alerts</h3>
      <div className="field check">
        <label>
          <input
            type="checkbox"
            checked={form.alerts.enabled}
            onChange={(e) => updateAlerts({ enabled: e.target.checked })}
          />
          Enable scheduled buy/sell alerts
        </label>
      </div>
      {form.alerts.enabled && (
        <>
          <div className="field">
            <label>Telegram bot token (leave as **** to keep the saved token)</label>
            <input
              type="password"
              value={form.alerts.telegram_bot_token}
              onChange={(e) => updateAlerts({ telegram_bot_token: e.target.value })}
              placeholder="123456:ABC-..."
            />
          </div>
          <div className="field">
            <label>Telegram chat id</label>
            <input
              value={form.alerts.telegram_chat_id}
              onChange={(e) => updateAlerts({ telegram_chat_id: e.target.value })}
              placeholder="e.g. 987654321"
            />
          </div>
          <div className="row">
            <div className="field">
              <label>RSI low (buy)</label>
              <input type="number" value={form.alerts.rsi_low} onChange={(e) => updateAlerts({ rsi_low: Number(e.target.value) })} />
            </div>
            <div className="field">
              <label>RSI high (sell)</label>
              <input type="number" value={form.alerts.rsi_high} onChange={(e) => updateAlerts({ rsi_high: Number(e.target.value) })} />
            </div>
          </div>
          <button className="secondary" onClick={onTestAlert} disabled={save.isPending}>Send test alert</button>
          {alertTest && <span className={`note ${alertTest.ok ? 'muted' : 'error'}`} style={{ marginLeft: 8 }}>{alertTest.ok ? '✓ ' : '✗ '}{alertTest.message}</span>}
        </>
      )}

      <h3>Truth Social signal</h3>
      <div className="field check">
        <label>
          <input
            type="checkbox"
            checked={form.truth_signal.enabled}
            onChange={(e) => updateTruth({ enabled: e.target.checked })}
          />
          Use Trump / Truth Social posts as a market-mood + mention signal
        </label>
      </div>
      {form.truth_signal.enabled && (
        <div className="field">
          <label>Lookback (hours)</label>
          <input
            type="number"
            value={form.truth_signal.lookback_hours}
            onChange={(e) => updateTruth({ lookback_hours: Number(e.target.value) })}
          />
        </div>
      )}

      <div className="settings-actions">
        <button onClick={onSave} disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save'}</button>
        <button className="secondary" onClick={onTest} disabled={save.isPending}>Test connection</button>
        {saved && <span className="note muted">Saved.</span>}
        {test && <span className={`note ${test.ok ? 'muted' : 'error'}`}>{test.ok ? '✓ ' : '✗ '}{test.message}</span>}
      </div>
      {save.isError && <p className="error">Save failed: {(save.error as Error).message}</p>}
    </div>
  );
}
