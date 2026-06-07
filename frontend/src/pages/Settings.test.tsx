import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Settings from './Settings';
import type { ProviderInfo, Settings as SettingsT } from '../types';

vi.mock('../api/client', () => ({
  api: {
    getSettings: vi.fn(),
    saveSettings: vi.fn(),
    listProviders: vi.fn(),
    listModels: vi.fn(),
    testProvider: vi.fn(),
    testAlert: vi.fn(),
    getMood: vi.fn(),
  },
}));

import { api } from '../api/client';

const SETTINGS: SettingsT = {
  active_provider: 'anthropic',
  providers: { anthropic: { model: 'claude-x', api_key: 'k', base_url: '' } },
  watchlist: ['AAPL'],
  indicator_params: { sma_windows: [50, 200], rsi_length: 14 },
  alerts: { enabled: false, channel: 'log', telegram_bot_token: '', telegram_chat_id: '', rsi_low: 30, rsi_high: 70 },
  truth_signal: { enabled: false, source_url: '', lookback_hours: 48 },
  screener: { enabled: true, top_n: 25, default_sector: null, rsi_low: 30, rsi_high: 70, weights: {} },
  network: { enabled: true, focus_top_n: 30, max_edges_per_company: 8, min_confidence: 0.4, weight: 0.5, alpha_event: 0.6, beta_state: 0.4 },
  evaluation: { enabled: true, horizons: [1, 5, 20], hold_band_pct: 2.0, score_scale_pct: 5.0 },
};

const PROVIDERS: ProviderInfo[] = [
  { id: 'anthropic', label: 'Anthropic (Claude)', configured: true, default_model: 'claude-x' },
];

beforeEach(() => {
  vi.mocked(api.getSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.saveSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.listProviders).mockResolvedValue(PROVIDERS);
  vi.mocked(api.listModels).mockResolvedValue({ models: ['claude-a', 'claude-b'], error: '' });
});

function renderSettings() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Settings />
    </QueryClientProvider>,
  );
}

describe('Settings fetch models', () => {
  it('fetches and renders the model dropdown', async () => {
    renderSettings();
    const btn = await screen.findByRole('button', { name: /fetch models/i });
    fireEvent.click(btn);
    await waitFor(() => expect(api.listModels).toHaveBeenCalledWith('anthropic'));
    await waitFor(() => {
      const opts = Array.from(document.querySelectorAll('#model-options option')).map((o) => o.getAttribute('value'));
      expect(opts).toEqual(['claude-a', 'claude-b']);
    });
  });
});
