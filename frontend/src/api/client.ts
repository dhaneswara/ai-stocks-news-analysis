import type {
  AgentEvent,
  AnalysisResult,
  EvaluationBoard,
  ImportReport,
  ImportSetSummary,
  KnowledgeGraph,
  MarketMood,
  OntologySummary,
  OntologyVersion,
  ProviderInfo,
  RescanEvent,
  ScreenBoard,
  Settings,
  SignalsSummary,
  SnapshotResult,
  Source,
  StockData,
  StockScore,
  TestResult,
  WatchlistRunEvent,
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
  getSectors: () => http<string[]>('/screen/sectors'),
  getScore: (ticker: string) => http<StockScore>(`/score/${encodeURIComponent(ticker)}`),
  getSignals: (ticker: string) => http<SignalsSummary>(`/signals/${encodeURIComponent(ticker)}`),
  snapshotEvaluation: () => http<SnapshotResult>('/evaluation/snapshot', { method: 'POST' }),
  getCompanyGraph: (ticker: string) =>
    http<KnowledgeGraph>(`/graph/company/${encodeURIComponent(ticker)}`),
  listOntologies: () => http<OntologySummary[]>('/graph/ontologies'),
  saveOntology: (v: OntologyVersion) =>
    http<OntologyVersion>('/graph/ontologies', { method: 'POST', body: JSON.stringify(v) }),
  loadOntology: (name: string, version?: string) =>
    http<OntologyVersion>(
      `/graph/ontologies/${encodeURIComponent(name)}${version ? `?version=${encodeURIComponent(version)}` : ''}`,
    ),
  deleteOntology: (name: string, version?: string) =>
    http<{ deleted: boolean }>(
      `/graph/ontologies/${encodeURIComponent(name)}${version ? `?version=${encodeURIComponent(version)}` : ''}`,
      { method: 'DELETE' },
    ),
  getActiveOntology: () => http<{ name: string | null }>('/graph/active'),
  setActiveOntology: (name: string | null) =>
    http<{ name: string | null }>('/graph/active', { method: 'PUT', body: JSON.stringify({ name }) }),
  importGraph: (name: string, payload: unknown) =>
    http<ImportReport>('/graph/import', { method: 'POST', body: JSON.stringify({ name, payload }) }),
  listImports: () => http<ImportSetSummary[]>('/graph/imports'),
  deleteImport: (id: string) =>
    http<{ deleted: boolean }>(`/graph/imports?set_id=${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getImportSet: (id: string) => http<KnowledgeGraph>(`/graph/imports/${encodeURIComponent(id)}`),
  refreshUniverse: () =>
    http<{ count: number; sectors: Record<string, number>; source: string }>('/universe/refresh', {
      method: 'POST',
    }),
  getEvaluation: () => http<EvaluationBoard>('/evaluation'),
  explainPrediction: (ticker: string, callDate: string, source: Source) =>
    http<{ explanation: string }>(
      `/evaluation/${encodeURIComponent(ticker)}/${encodeURIComponent(callDate)}/explain?source=${encodeURIComponent(source)}`,
      { method: 'POST' },
    ),
  deleteTracked: (ticker: string) =>
    http<{ deleted: number }>(`/evaluation/${encodeURIComponent(ticker)}`, { method: 'DELETE' }),
  clearEvaluation: () =>
    http<{ predictions: number; evals: number }>('/evaluation', { method: 'DELETE' }),
};

export interface DeepStreamHandlers {
  onEvent: (event: AgentEvent) => void;
  onError: (message: string) => void;
}

/** Open an SSE stream for an agentic deep analysis. Returns a closer the caller MUST keep and
 *  invoke on unmount — EventSource auto-reconnects otherwise, which would restart the analysis. */
export function streamDeepAnalysis(
  ticker: string,
  period: string,
  handlers: DeepStreamHandlers,
): () => void {
  const url =
    `${BASE}/analyze/${encodeURIComponent(ticker)}/deep/stream?period=${encodeURIComponent(period)}`;
  const es = new EventSource(url);
  const forward = (type: AgentEvent['type']) => (e: MessageEvent) => {
    try {
      handlers.onEvent({ ...(JSON.parse(e.data) as AgentEvent), type });
    } catch {
      handlers.onError('Malformed event from server');
    }
  };
  es.addEventListener('step', forward('step') as EventListener);
  es.addEventListener('final', ((e: MessageEvent) => {
    forward('final')(e);
    es.close(); // terminal — close before EventSource auto-reconnects
  }) as EventListener);
  es.addEventListener('error', ((e: MessageEvent) => {
    if (e.data) forward('error')(e);          // server-sent `event: error` (has data)
    else handlers.onError('Connection error'); // native connection failure (no data)
    es.close();
  }) as EventListener);
  return () => es.close();
}

export interface WatchlistStreamHandlers {
  onEvent: (event: WatchlistRunEvent) => void;
  onError: (message: string) => void;
}

export interface RescanStreamHandlers {
  onEvent: (event: RescanEvent) => void;
  onError: (message: string) => void;
}

/** Open the SSE stream for a Discover board rescan. Returns a closer the caller MUST keep
 *  and invoke on unmount/stop — EventSource auto-reconnects otherwise, which would restart
 *  the scan. Closing mid-scan aborts it server-side; nothing is saved. */
export function streamRescan(
  sector: string | undefined,
  handlers: RescanStreamHandlers,
): () => void {
  const url = `${BASE}/screen/rescan/stream${sector ? `?sector=${encodeURIComponent(sector)}` : ''}`;
  const es = new EventSource(url);
  const forward = (type: RescanEvent['type']) => (e: MessageEvent) => {
    try {
      handlers.onEvent({ ...(JSON.parse(e.data) as RescanEvent), type });
    } catch {
      handlers.onError('Malformed event from server');
    }
  };
  es.addEventListener('tick', forward('tick') as EventListener);
  es.addEventListener('done', ((e: MessageEvent) => {
    forward('done')(e);
    es.close(); // terminal — close before EventSource auto-reconnects
  }) as EventListener);
  es.addEventListener('error', ((e: MessageEvent) => {
    if (e.data) forward('error')(e);          // server-sent scan failure (has data)
    else handlers.onError('Connection error'); // native connection failure (no data)
    es.close();
  }) as EventListener);
  return () => es.close();
}

/** Open the SSE stream for a watchlist-wide LLM batch run. Returns a closer the caller
 *  MUST keep and invoke on unmount/stop — EventSource auto-reconnects otherwise, which
 *  would restart the batch from the top. */
export function streamWatchlistRun(
  mode: 'fast' | 'deep',
  handlers: WatchlistStreamHandlers,
): () => void {
  const es = new EventSource(`${BASE}/analyze/watchlist/stream?mode=${mode}`);
  const forward = (type: WatchlistRunEvent['type']) => (e: MessageEvent) => {
    try {
      handlers.onEvent({ ...(JSON.parse(e.data) as WatchlistRunEvent), type });
    } catch {
      handlers.onError('Malformed event from server');
    }
  };
  es.addEventListener('start', forward('start') as EventListener);
  es.addEventListener('ticker', forward('ticker') as EventListener);
  es.addEventListener('done', ((e: MessageEvent) => {
    forward('done')(e);
    es.close(); // terminal — close before EventSource auto-reconnects
  }) as EventListener);
  es.addEventListener('error', ((e: MessageEvent) => {
    if (e.data) forward('error')(e);          // server-sent run-level error (has data)
    else handlers.onError('Connection error'); // native connection failure (no data)
    es.close();
  }) as EventListener);
  return () => es.close();
}
