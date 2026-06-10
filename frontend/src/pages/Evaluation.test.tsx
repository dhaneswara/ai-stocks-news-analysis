import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import Evaluation from './Evaluation';
import type { EvaluationBoard } from '../types';

vi.mock('../api/client', () => ({
  api: {
    getEvaluation: vi.fn(),
    explainPrediction: vi.fn(),
    deleteTracked: vi.fn(),
  },
}));

import { api } from '../api/client';

const BOARD: EvaluationBoard = {
  as_of: '2026-06-07T00:00:00Z',
  sources: {},
  companies: [
    {
      rollup: {
        ticker: 'AAPL', n_calls: 1, n_matured: 2, hit_rate: 50.0, avg_score: 45.0,
        grade: 'Mixed', overconfident: true, latest_recommendation: 'sell',
        latest_call_date: '2026-06-01',
      },
      by_source: {},
      calls: [
        {
          ticker: 'AAPL', call_date: '2026-06-01', provider: 'anthropic', model: 'm',
          recommendation: 'sell', confidence: 0.9, sentiment: 'bearish', entry_price: 100,
          source: 'llm_fast',
          results: [
            { horizon: 1, status: 'final', eval_date: '2026-06-02', return_pct: 5.0, hit: false, score: 0 },
            { horizon: 5, status: 'final', eval_date: '2026-06-08', return_pct: -3.0, hit: true, score: 80 },
            { horizon: 20, status: 'pending' },
          ],
        },
      ],
    },
  ],
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Evaluation />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.getEvaluation).mockResolvedValue(BOARD);
  vi.mocked(api.explainPrediction).mockResolvedValue({ explanation: 'Missed an earnings beat.' });
  vi.mocked(api.deleteTracked).mockResolvedValue({ deleted: 1 });
});

describe('Evaluation page', () => {
  it('shows the board and expands a company to reveal calls', async () => {
    renderPage();
    const row = await screen.findByText('AAPL');
    fireEvent.click(row);
    // The call's horizon chips appear once expanded
    expect(await screen.findByText(/1d/)).toBeInTheDocument();
    expect(screen.getByText(/5d/)).toBeInTheDocument();
    expect(screen.getByText(/20d/)).toBeInTheDocument();
  });

  it('runs an LLM post-mortem on a missed call', async () => {
    renderPage();
    fireEvent.click(await screen.findByText('AAPL'));
    const explainBtn = await screen.findByRole('button', { name: /explain miss/i });
    fireEvent.click(explainBtn);
    expect(await screen.findByText(/missed an earnings beat/i)).toBeInTheDocument();
    expect(api.explainPrediction).toHaveBeenCalledWith('AAPL', '2026-06-01', 'llm_fast');
  });

  it('renders SourceScoreboard cards and filter empty-state', async () => {
    const boardWithSources: EvaluationBoard = {
      ...BOARD,
      sources: {
        technical: { n_calls: 4, n_matured: 3, hit_rate: 66.7, avg_score: 61.2, grade: 'Mixed' },
      },
    };
    vi.mocked(api.getEvaluation).mockResolvedValue(boardWithSources);

    renderPage();

    // Scoreboard card assertions
    // "Technical" appears in the card label and in the filter button; both are fine
    await screen.findByText(/66\.7% hit rate/);
    expect(screen.getAllByText('Technical').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/66\.7% hit rate/)).toBeInTheDocument();
    expect(screen.getByText(/4 calls · 3 scored/)).toBeInTheDocument();
    // "Mixed" appears in the scoreboard card and in the board row — both are expected
    expect(screen.getAllByText('Mixed').length).toBeGreaterThanOrEqual(1);

    // Click the "LLM deep" filter button
    const deepBtn = screen.getByRole('button', { name: 'LLM deep' });
    fireEvent.click(deepBtn);

    // Expand AAPL company detail — fixture call is llm_fast, so filter=llm_deep → empty
    fireEvent.click(await screen.findByText('AAPL'));
    expect(await screen.findByText('No calls from this source yet.')).toBeInTheDocument();
  });
});
