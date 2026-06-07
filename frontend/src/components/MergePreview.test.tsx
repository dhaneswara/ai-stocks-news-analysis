import { expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MergePreview } from './MergePreview';
import type { KnowledgeGraph, StockScore } from '../types';

const board: StockScore[] = [
  { ticker: 'NVDA', name: 'NVIDIA Corporation', sector: 'Tech', price: 1, change_pct: 0, score: 70, direction: 'buy', reasons: [], components: {}, as_of: '', net: 0 },
];
const working: KnowledgeGraph = { as_of: 't', scope: 'company:AAPL', built: 1, skipped: 0, nodes: ['AAPL'], node_meta: {}, edges: [] };
const importSet: KnowledgeGraph = {
  as_of: 't', scope: 'imported', built: 1, skipped: 0, nodes: ['AAPL', 'ext:nvidia'],
  node_meta: { 'ext:nvidia': { label: 'Nvidia', kind: 'company', source: 'imported' } },
  edges: [{ source: 'AAPL', target: 'ext:nvidia', type: 'partner', sentiment: 'positive', weight: 1, confidence: 1, evidence: '', url: '', as_of: '', origin: 'imported' }],
};

it('applies with the suggested Discover link by default', () => {
  const onApply = vi.fn();
  render(<MergePreview working={working} importSet={importSet} board={board} onApply={onApply} onCancel={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: /apply merge/i }));
  const merged = onApply.mock.calls[0][0] as KnowledgeGraph;
  expect(merged.nodes).toContain('NVDA');
  expect(merged.nodes).not.toContain('ext:nvidia');
});

it('keeps it external when the dropdown is set to keep', () => {
  const onApply = vi.fn();
  render(<MergePreview working={working} importSet={importSet} board={board} onApply={onApply} onCancel={vi.fn()} />);
  fireEvent.change(screen.getByDisplayValue(/NVDA/), { target: { value: 'ext:nvidia' } });
  fireEvent.click(screen.getByRole('button', { name: /apply merge/i }));
  const merged = onApply.mock.calls[0][0] as KnowledgeGraph;
  expect(merged.nodes).toContain('ext:nvidia');
});
