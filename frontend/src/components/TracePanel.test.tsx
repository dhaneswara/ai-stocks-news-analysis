import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TracePanel } from './TracePanel';
import type { AgentStep } from '../types';

const step: AgentStep = {
  index: 0, thought: 'check the news', action: 'fetch_news',
  action_args: { query: 'x' }, observation: 'NVDA beats', is_final: false, elapsed_ms: 0,
};

it('renders each step with its thought, action and observation', () => {
  render(<TracePanel running={false} steps={[step]} />);
  expect(screen.getByText('check the news')).toBeInTheDocument();
  expect(screen.getByText('fetch_news')).toBeInTheDocument();
  expect(screen.getByText('NVDA beats')).toBeInTheDocument();
});

it('shows live progress while running', () => {
  render(<TracePanel running steps={[]} />);
  expect(screen.getByText(/step 0\s*\/\s*6/i)).toBeInTheDocument();
});

it('falls back to the raw model output when a step has no parsed content', () => {
  const rawStep: AgentStep = {
    index: 0, thought: '', action: null, action_args: {}, observation: null,
    is_final: false, elapsed_ms: 0, raw: 'model said something off-format',
  };
  render(<TracePanel running={false} steps={[rawStep]} />);
  expect(screen.getByText('model said something off-format')).toBeInTheDocument();
});
