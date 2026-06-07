import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { SavedGraphVersion, Settings } from '../types';

export function useStock(ticker: string, period = '5y') {
  return useQuery({
    queryKey: ['stock', ticker, period],
    queryFn: () => api.getStock(ticker, period),
    enabled: ticker.length > 0,
    retry: false,
  });
}

export function useAnalyze(ticker: string, period = '5y') {
  return useMutation({ mutationFn: () => api.analyze(ticker, period) });
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

export function useListModels() {
  return useMutation({ mutationFn: (id: string) => api.listModels(id) });
}

export function useSectors() {
  return useQuery({ queryKey: ['sectors'], queryFn: api.getSectors });
}

export function useScreen(sector?: string, direction?: string, limit?: number) {
  return useQuery({
    queryKey: ['screen', sector ?? '', direction ?? '', limit ?? ''],
    queryFn: () => api.getScreen(sector, direction, limit),
  });
}

export function useRescan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sector?: string) => api.rescan(sector),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['screen'] }),
  });
}

export function useRefreshUniverse() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.refreshUniverse(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sectors'] }),
  });
}

export function useEgoGraph() {
  return useMutation({ mutationFn: (ticker: string) => api.getCompanyGraph(ticker) });
}

export function useSavedGraphs() {
  return useQuery({ queryKey: ['savedGraphs'], queryFn: api.listSavedGraphs });
}

export function useSaveGraph() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: SavedGraphVersion) => api.saveGraph(v),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['savedGraphs'] }),
  });
}

export function useLoadSavedGraph() {
  return useMutation({
    mutationFn: ({ root, version }: { root: string; version?: string }) =>
      api.loadSavedGraph(root, version),
  });
}

export function useDeleteSavedGraph() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ root, version }: { root: string; version?: string }) =>
      api.deleteSavedGraph(root, version),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['savedGraphs'] }),
  });
}

export function useEvaluation() {
  return useQuery({ queryKey: ['evaluation'], queryFn: api.getEvaluation });
}

export function useExplainPrediction() {
  return useMutation({
    mutationFn: ({ ticker, callDate }: { ticker: string; callDate: string }) =>
      api.explainPrediction(ticker, callDate),
  });
}

export function useDeleteTracked() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) => api.deleteTracked(ticker),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['evaluation'] }),
  });
}
