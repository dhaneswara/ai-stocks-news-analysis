import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { EvaluationBoard } from './EvaluationBoard';
import type { CompanyEvaluation } from '../types';

const COMPANIES: CompanyEvaluation[] = [
  {
    rollup: {
      ticker: 'AAPL', n_calls: 3, n_matured: 6, hit_rate: 66.7, avg_score: 72.0,
      grade: 'Strong', overconfident: false, latest_recommendation: 'buy',
      latest_call_date: '2026-06-05',
    },
    calls: [],
  },
  {
    rollup: {
      ticker: 'TSLA', n_calls: 1, n_matured: 0, hit_rate: null, avg_score: null,
      grade: null, overconfident: false, latest_recommendation: 'sell',
      latest_call_date: '2026-06-06',
    },
    calls: [],
  },
];

describe('EvaluationBoard', () => {
  it('renders a row per company with grade and hit-rate', () => {
    render(<EvaluationBoard companies={COMPANIES} selected={null} onSelect={() => {}} />);
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('Strong')).toBeInTheDocument();
    expect(screen.getByText('66.7%')).toBeInTheDocument();
  });

  it('shows a dash for companies with no matured calls', () => {
    render(<EvaluationBoard companies={COMPANIES} selected={null} onSelect={() => {}} />);
    // TSLA row has no hit-rate yet
    const cells = screen.getAllByText('—');
    expect(cells.length).toBeGreaterThan(0);
  });

  it('calls onSelect when a row is clicked', () => {
    const onSelect = vi.fn();
    render(<EvaluationBoard companies={COMPANIES} selected={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText('AAPL'));
    expect(onSelect).toHaveBeenCalledWith('AAPL');
  });

  it('renders an empty hint when there are no companies', () => {
    render(<EvaluationBoard companies={[]} selected={null} onSelect={() => {}} />);
    expect(screen.getByText(/no tracked calls yet/i)).toBeInTheDocument();
  });
});
