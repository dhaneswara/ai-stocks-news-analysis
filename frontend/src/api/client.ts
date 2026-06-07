import type {
  AnalysisResult,
  EvaluationBoard,
  ImportReport,
  ImportSetSummary,
  KnowledgeGraph,
  MarketMood,
  ProviderInfo,
  SavedGraphSummary,
  SavedGraphVersion,
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
  listModels: (id: string) =>
    http<{ models: string[]; error: string }>(`/providers/${encodeURIComponent(id)}/models`),
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
  getCompanyGraph: (ticker: string) =>
    http<KnowledgeGraph>(`/graph/company/${encodeURIComponent(ticker)}`),
  listSavedGraphs: () => http<SavedGraphSummary[]>('/graph/saved'),
  saveGraph: (v: SavedGraphVersion) =>
    http<SavedGraphVersion>('/graph/saved', { method: 'POST', body: JSON.stringify(v) }),
  loadSavedGraph: (root: string, version?: string) =>
    http<SavedGraphVersion>(
      `/graph/saved/${encodeURIComponent(root)}${version ? `?version=${encodeURIComponent(version)}` : ''}`,
    ),
  deleteSavedGraph: (root: string, version?: string) =>
    http<{ deleted: boolean }>(
      `/graph/saved/${encodeURIComponent(root)}${version ? `?version=${encodeURIComponent(version)}` : ''}`,
      { method: 'DELETE' },
    ),
  importGraph: (name: string, payload: unknown) =>
    http<ImportReport>('/graph/import', { method: 'POST', body: JSON.stringify({ name, payload }) }),
  listImports: () => http<ImportSetSummary[]>('/graph/imports'),
  deleteImport: (id: string) =>
    http<{ deleted: boolean }>(`/graph/imports?set_id=${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getOverlay: () => http<KnowledgeGraph>('/graph?scope=imported'),
  refreshUniverse: () =>
    http<{ count: number; sectors: Record<string, number>; source: string }>('/universe/refresh', {
      method: 'POST',
    }),
  getEvaluation: () => http<EvaluationBoard>('/evaluation'),
  explainPrediction: (ticker: string, callDate: string) =>
    http<{ explanation: string }>(
      `/evaluation/${encodeURIComponent(ticker)}/${encodeURIComponent(callDate)}/explain`,
      { method: 'POST' },
    ),
  deleteTracked: (ticker: string) =>
    http<{ deleted: number }>(`/evaluation/${encodeURIComponent(ticker)}`, { method: 'DELETE' }),
};
