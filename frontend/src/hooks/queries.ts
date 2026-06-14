import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { OntologyVersion, ScreenBoard, Settings, Source } from '../types';

export function useStock(ticker: string, period = '5y') {
  return useQuery({
    queryKey: ['stock', ticker, period],
    queryFn: () => api.getStock(ticker, period),
    enabled: ticker.length > 0,
    retry: false,
  });
}

export function useAnalyze(ticker: string, period = '5y') {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.analyze(ticker, period),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['signals', ticker] });
      qc.invalidateQueries({ queryKey: ['evaluation'] });
      qc.invalidateQueries({ queryKey: ['analysis', ticker] });
    },
  });
}

export function useSettings() {
  return useQuery({ queryKey: ['settings'], queryFn: api.getSettings });
}

export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (s: Settings) => api.saveSettings(s),
    onSuccess: (data) => qc.setQueryData(['settings'], data),
  });
}

export function useWatchlist() {
  const settings = useSettings();
  const save = useSaveSettings();
  const list = settings.data?.watchlist ?? [];
  const add = (t: string) => {
    const s = settings.data;
    if (!s || s.watchlist.includes(t)) return;
    save.mutate({ ...s, watchlist: [...s.watchlist, t] });
  };
  const remove = (t: string) => {
    const s = settings.data;
    if (!s || !s.watchlist.includes(t)) return;
    save.mutate({ ...s, watchlist: s.watchlist.filter((x) => x !== t) });
  };
  return { list, add, remove, error: save.error, isError: save.isError };
}

export function useProviders() {
  return useQuery({ queryKey: ['providers'], queryFn: api.listProviders });
}

export function useNewsProviders() {
  return useQuery({ queryKey: ['newsProviders'], queryFn: api.getNewsProviders });
}

export function useListModels() {
  return useMutation({ mutationFn: (id: string) => api.listModels(id) });
}

export function useSectors() {
  return useQuery({ queryKey: ['sectors'], queryFn: api.getSectors });
}

export function useScreen(sector?: string, direction?: string, limit?: number, scope?: string) {
  return useQuery({
    queryKey: ['screen', sector ?? '', direction ?? '', limit ?? '', scope ?? ''],
    queryFn: () => api.getScreen(sector, direction, limit, scope),
  });
}

export function usePortfolioTickers() {
  return useQuery({ queryKey: ['portfolio', 'tickers'], queryFn: api.getPortfolioTickers });
}

export function useScore(ticker: string) {
  return useQuery({
    queryKey: ['score', ticker],
    queryFn: () => api.getScore(ticker),
    enabled: ticker.length > 0,
    retry: false,
  });
}

// Which saved snapshot a board's scope key segment reads from — mirrors the backend's
// `snap_scope = "portfolio" if scope == "portfolio" else "all"` (store.upsert_score / GET /screen).
const snapScope = (s: unknown) => (s === 'portfolio' ? 'portfolio' : 'all');

export function useRescanTicker(scope?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) => api.rescanTicker(ticker, scope),
    onSuccess: (fresh) => {
      // Patch the row only in cached boards backed by the SAME snapshot the server just persisted
      // (key[4] is the scope segment of ['screen', sector, direction, limit, scope]); re-sort to
      // match the server. No refetch — and don't touch the other scope's board, whose on-disk
      // snapshot was not updated, or it would diverge until its next refetch.
      qc.setQueriesData<ScreenBoard>(
        { queryKey: ['screen'], predicate: (q) => snapScope(q.queryKey[4]) === snapScope(scope) },
        (board) => {
          if (!board) return board;          // no cached board for this view — leave it untouched
          const i = board.items.findIndex(
            (s) => s.ticker.toUpperCase() === fresh.ticker.toUpperCase(),
          );
          if (i === -1) return board;
          const items = [...board.items];
          items[i] = fresh;
          items.sort((a, b) => b.score - a.score);
          return { ...board, items };
        },
      );
    },
  });
}

export function useRefreshUniverse() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.refreshUniverse(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sectors'] }),
  });
}

export function useCustomCompanies() {
  return useQuery({ queryKey: ['customCompanies'], queryFn: api.listCustomCompanies });
}

export function useAddCustomCompany() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) => api.addCustomCompany(ticker),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['customCompanies'] });
      qc.invalidateQueries({ queryKey: ['sectors'] });
    },
  });
}

export function useDeleteCustomCompany() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) => api.deleteCustomCompany(ticker),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['customCompanies'] }),
  });
}

export function useEgoGraph() {
  return useMutation({
    mutationFn: ({ ticker, refresh }: { ticker: string; refresh?: boolean }) =>
      api.getCompanyGraph(ticker, refresh),
  });
}

const ONTOLOGY_INVALIDATES = [['ontologies'], ['screen'], ['score'], ['signals']] as const;

/** Mutating an ontology can re-bake the board server-side (when it's the ACTIVE one) — refresh
 *  the ontology list and every score reader. */
function invalidateOntologyWorld(qc: ReturnType<typeof useQueryClient>) {
  for (const key of ONTOLOGY_INVALIDATES) qc.invalidateQueries({ queryKey: [...key] });
}

export function useOntologies() {
  return useQuery({ queryKey: ['ontologies'], queryFn: api.listOntologies });
}

export function useActiveOntology() {
  return useQuery({ queryKey: ['ontologies', 'active'], queryFn: api.getActiveOntology });
}

export function useSaveOntology() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: OntologyVersion) => api.saveOntology(v),
    onSuccess: () => invalidateOntologyWorld(qc),
  });
}

export function useLoadOntology() {
  return useMutation({
    mutationFn: ({ name, version }: { name: string; version?: string }) =>
      api.loadOntology(name, version),
  });
}

export function useDeleteOntology() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, version }: { name: string; version?: string }) =>
      api.deleteOntology(name, version),
    onSuccess: () => invalidateOntologyWorld(qc),
  });
}

export function useSetActiveOntology() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string | null) => api.setActiveOntology(name),
    onSuccess: () => invalidateOntologyWorld(qc),
  });
}

export function useImports() {
  return useQuery({ queryKey: ['graphImports'], queryFn: api.listImports });
}

export function useImportGraph() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, payload }: { name: string; payload: unknown }) => api.importGraph(name, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['graphImports'] });
    },
  });
}

export function useDeleteImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteImport(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['graphImports'] });
    },
  });
}

export function useEvaluation() {
  return useQuery({ queryKey: ['evaluation'], queryFn: api.getEvaluation });
}

export function useExplainPrediction() {
  return useMutation({
    mutationFn: ({ ticker, callDate, source }: { ticker: string; callDate: string; source: Source }) =>
      api.explainPrediction(ticker, callDate, source),
  });
}

export function useSignals(ticker: string) {
  return useQuery({
    queryKey: ['signals', ticker],
    queryFn: () => api.getSignals(ticker),
    enabled: ticker.length > 0,
    retry: false,
  });
}

export function useLastAnalysis(ticker: string) {
  return useQuery({
    queryKey: ['analysis', ticker],
    queryFn: () => api.getLastAnalysis(ticker),
    enabled: ticker.length > 0,
    retry: false,
  });
}

export function useSnapshotEvaluation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.snapshotEvaluation(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['evaluation'] }),
    onError: (e) => console.warn('signal snapshot failed:', e),
  });
}

export function useDeleteTracked() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) => api.deleteTracked(ticker),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['evaluation'] }),
  });
}

export function useClearEvaluation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.clearEvaluation(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['evaluation'] });
      // The Dashboard signals strip reads the same store — clear its caches too.
      qc.invalidateQueries({ queryKey: ['signals'] });
    },
  });
}
