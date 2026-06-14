import { createContext, useContext } from 'react';
import type { ChartRange } from '../components/PriceChart';
import type { AnalysisResult, Signal } from '../types';

export interface DashboardState {
  ticker: string;
  setTicker: (t: string) => void;
  range: ChartRange;
  setRange: (r: ChartRange) => void;
  analysis: AnalysisResult | null;
  setAnalysis: (a: AnalysisResult | null) => void;
  selected: Signal | null;
  setSelected: (s: Signal | null) => void;
}

export const DashboardStateContext = createContext<DashboardState | null>(null);

export function useDashboardState(): DashboardState {
  const ctx = useContext(DashboardStateContext);
  if (!ctx) throw new Error('useDashboardState must be used within a DashboardStateProvider');
  return ctx;
}
