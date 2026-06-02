import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Settings } from '../types';

export function useStock(ticker: string, period = '2y') {
  return useQuery({
    queryKey: ['stock', ticker, period],
    queryFn: () => api.getStock(ticker, period),
    enabled: ticker.length > 0,
    retry: false,
  });
}

export function useAnalyze(ticker: string, period = '2y') {
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

export function useProviders() {
  return useQuery({ queryKey: ['providers'], queryFn: api.listProviders });
}
