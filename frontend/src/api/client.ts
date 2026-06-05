import type {
  AnalysisResult,
  MarketMood,
  ProviderInfo,
  ScreenBoard,
  Settings,
  StockData,
  TestResult,
} from '../types';

const BASE = (import.meta.env.VITE_API_BASE as string) || 'http://localhost:8000/api';

export async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail ?? detail;
    } catch {
      /* response had no JSON body */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export const api = {
  getStock: (ticker: string, period = '2y') =>
    http<StockData>(`/stock/${encodeURIComponent(ticker)}?period=${period}`),
  analyze: (ticker: string, period = '2y') =>
    http<AnalysisResult>(`/analyze/${encodeURIComponent(ticker)}?period=${period}`, {
      method: 'POST',
    }),
  getSettings: () => http<Settings>('/settings'),
  saveSettings: (s: Settings) =>
    http<Settings>('/settings', { method: 'PUT', body: JSON.stringify(s) }),
  listProviders: () => http<ProviderInfo[]>('/providers'),
  testProvider: (id: string) =>
    http<TestResult>(`/providers/${encodeURIComponent(id)}/test`, { method: 'POST' }),
  testAlert: () => http<TestResult>('/alerts/test', { method: 'POST' }),
  getMood: () => http<{ enabled: boolean; post_count: number; mood: MarketMood | null }>('/truth/mood'),
  getScreen: (sector?: string, direction?: string, limit?: number) => {
    const q = new URLSearchParams();
    if (sector) q.set('sector', sector);
    if (direction) q.set('direction', direction);
    if (limit != null) q.set('limit', String(limit));
    const qs = q.toString();
    return http<ScreenBoard>(`/screen${qs ? `?${qs}` : ''}`);
  },
  rescan: (sector?: string) =>
    http<ScreenBoard>(`/screen/rescan${sector ? `?sector=${encodeURIComponent(sector)}` : ''}`, {
      method: 'POST',
    }),
  getSectors: () => http<string[]>('/screen/sectors'),
};
