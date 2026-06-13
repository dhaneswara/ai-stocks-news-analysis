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
    testNews: vi.fn(),
    getNewsProviders: vi.fn(),
  },
}));

import { api } from '../api/client';

const SETTINGS: SettingsT = {
  active_provider: 'anthropic',
  providers: {
    anthropic: { model: 'claude-x', api_key: 'k', base_url: '' },
    openai: { model: 'gpt-x', api_key: 'k2', base_url: '' },
  },
  watchlist: ['AAPL'],
  indicator_params: { sma_windows: [50, 200], rsi_length: 14 },
  alerts: { enabled: false, channel: 'log', telegram_bot_token: '', telegram_chat_id: '', rsi_low: 30, rsi_high: 70 },
  truth_signal: { enabled: false, source_url: '', lookback_hours: 48 },
  screener: { enabled: true, top_n: 25, default_sector: null, rsi_low: 30, rsi_high: 70, weights: {} },
  network: { enabled: true, focus_top_n: 30, max_edges_per_company: 8, min_confidence: 0.4, weight: 0.5, alpha_event: 0.6, beta_state: 0.4, symmetric_types: ['competitor', 'partner', 'other'] },
  evaluation: { enabled: true, horizons: [1, 5, 20], hold_band_pct: 2.0, score_scale_pct: 5.0 },
  news: {
    active_provider: 'google',
    providers: { google: {api_key:'',mcp_url:''}, tavily: {api_key:'',mcp_url:''}, exa: {api_key:'',mcp_url:''}, you: {api_key:'',mcp_url:''} },
    news_recency_days: 90,
  },
};

const PROVIDERS: ProviderInfo[] = [
  { id: 'anthropic', label: 'Anthropic (Claude)', configured: true, default_model: 'claude-x' },
  { id: 'openai', label: 'OpenAI', configured: true, default_model: 'gpt-x' },
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

describe('Settings news source', () => {
  it('switches news provider and shows the API key field + recency', async () => {
    renderSettings();
    const select = await screen.findByLabelText(/news source/i);
    fireEvent.change(select, { target: { value: 'tavily' } });
    expect(screen.getByLabelText(/news api key/i)).toBeInTheDocument();
    const recency = screen.getByLabelText(/news recency/i);
    fireEvent.change(recency, { target: { value: '30' } });
    expect((recency as HTMLInputElement).value).toBe('30');
  });
});

describe('Settings fetch models', () => {
  it('fetches and renders the model dropdown', async () => {
    renderSettings();
    const btn = await screen.findByRole('button', { name: /fetch models/i });
    fireEvent.click(btn);
    await waitFor(() => expect(api.listModels).toHaveBeenCalledWith('anthropic'));
    // The fetched models render as real <select> options (pick-only dropdown).
    expect(await screen.findByRole('option', { name: 'claude-a' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'claude-b' })).toBeInTheDocument();
  });

  it('clears the fetched-models status when the active provider changes', async () => {
    renderSettings();
    fireEvent.click(await screen.findByRole('button', { name: /fetch models/i }));
    expect(await screen.findByText(/2 models/)).toBeInTheDocument();
    // Switching the active provider must clear the stale "✓ N models" status.
    fireEvent.change(document.querySelector('select')!, { target: { value: 'openai' } });
    await waitFor(() => expect(screen.queryByText(/2 models/)).not.toBeInTheDocument());
  });
});
