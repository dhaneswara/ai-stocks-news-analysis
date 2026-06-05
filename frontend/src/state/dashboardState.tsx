import { createContext, useContext, useState, type ReactNode } from 'react';
import type { ChartRange } from '../components/PriceChart';
import type { AnalysisResult, Signal } from '../types';

interface DashboardState {
  ticker: string;
  setTicker: (t: string) => void;
  range: ChartRange;
  setRange: (r: ChartRange) => void;
  analysis: AnalysisResult | null;
  setAnalysis: (a: AnalysisResult | null) => void;
  selected: Signal | null;
  setSelected: (s: Signal | null) => void;
}

const DashboardStateContext = createContext<DashboardState | null>(null);

// Holds the Dashboard's view-state (ticker, chart range, the LLM analysis, and the
// selected signal) ABOVE the router. React Router unmounts the Dashboard route when
// you switch to Discover/Settings, which would otherwise discard the in-progress
// analysis; keeping it here lets it survive the round-trip.
export function DashboardStateProvider({ children }: { children: ReactNode }) {
  const [ticker, setTicker] = useState('');
  const [range, setRange] = useState<ChartRange>('2Y');
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [selected, setSelected] = useState<Signal | null>(null);
  return (
    <DashboardStateContext.Provider
      value={{ ticker, setTicker, range, setRange, analysis, setAnalysis, selected, setSelected }}
    >
      {children}
    </DashboardStateContext.Provider>
  );
}

export function useDashboardState(): DashboardState {
  const ctx = useContext(DashboardStateContext);
  if (!ctx) throw new Error('useDashboardState must be used within a DashboardStateProvider');
  return ctx;
}
