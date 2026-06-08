import { useCallback, useEffect, useRef, useState } from 'react';
import { streamDeepAnalysis } from '../api/client';
import type { AgentStep, AnalysisResult } from '../types';

export interface DeepAnalyzeState {
  steps: AgentStep[];
  result: AnalysisResult | null;
  running: boolean;
  error: string | null;
  fellBack: boolean;
}

const IDLE: DeepAnalyzeState = { steps: [], result: null, running: false, error: null, fellBack: false };

export function useDeepAnalyze(ticker: string, period: string) {
  const [state, setState] = useState<DeepAnalyzeState>(IDLE);
  const closeRef = useRef<(() => void) | null>(null);

  const start = useCallback(() => {
    closeRef.current?.();
    setState({ ...IDLE, running: true });
    closeRef.current = streamDeepAnalysis(ticker, period, {
      onEvent: (e) => {
        if (e.type === 'step' && e.step) {
          setState((s) => ({ ...s, steps: [...s.steps, e.step as AgentStep] }));
        } else if (e.type === 'final') {
          setState((s) => ({
            ...s, running: false, result: e.result ?? null, fellBack: e.trace?.fell_back ?? false,
          }));
        } else if (e.type === 'error') {
          setState((s) => ({ ...s, running: false, error: e.message || 'Analysis error' }));
        }
      },
      onError: (message) => setState((s) => ({ ...s, running: false, error: message })),
    });
  }, [ticker, period]);

  useEffect(() => () => closeRef.current?.(), []); // close the stream on unmount

  return { ...state, start };
}
