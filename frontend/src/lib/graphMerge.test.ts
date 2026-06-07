import { describe, expect, it } from 'vitest';
import { applyMerge, planMerge } from './graphMerge';
import type { KnowledgeGraph, StockScore } from '../types';

const board: StockScore[] = [
  { ticker: 'AAPL', name: 'Apple', sector: 'Tech', price: 1, change_pct: 0, score: 80, direction: 'buy', reasons: [], components: {}, as_of: '', net: 0 },
  { ticker: 'NVDA', name: 'NVIDIA Corporation', sector: 'Tech', price: 1, change_pct: 0, score: 70, direction: 'buy', reasons: [], components: {}, as_of: '', net: 0 },
];

const working: KnowledgeGraph = {
  as_of: 't', scope: 'company:AAPL', built: 1, skipped: 0,
  nodes: ['AAPL', 'NVDA'],
  node_meta: {},
  edges: [{ source: 'AAPL', target: 'NVDA', type: 'partner', sentiment: 'positive', weight: 1, confidence: 1, evidence: 'news', url: '', as_of: '', origin: 'extracted' }],
};

// import has NVDA as an unresolved external node + a new edge + a duplicate edge with different sentiment
const importSet: KnowledgeGraph = {
  as_of: 't', scope: 'imported', built: 1, skipped: 0,
  nodes: ['AAPL', 'ext:nvidia', 'ext:foundry'],
  node_meta: {
    'ext:nvidia': { label: 'Nvidia', kind: 'company', source: 'imported' },
    'ext:foundry': { label: 'Foundry Co', kind: 'private_company', source: 'imported' },
  },
  edges: [
    { source: 'AAPL', target: 'ext:nvidia', type: 'partner', sentiment: 'negative', weight: 1, confidence: 1, evidence: 'imp', url: '', as_of: '', origin: 'imported' },
    { source: 'ext:nvidia', target: 'ext:foundry', type: 'supplier', sentiment: 'positive', weight: 1, confidence: 1, evidence: '', url: '', as_of: '', origin: 'imported' },
  ],
};

describe('planMerge', () => {
  it('suggests a Discover ticker for a name-matched external node', () => {
    const { links } = planMerge(working, importSet, board);
    const nv = links.find((l) => l.importId === 'ext:nvidia')!;
    expect(nv.suggestion).toBe('NVDA');
    expect(nv.resolved).toBe('NVDA');
    const fo = links.find((l) => l.importId === 'ext:foundry')!;
    expect(fo.suggestion).toBeNull();
    expect(fo.resolved).toBe('ext:foundry');
  });
  it('emits no row for a node that is already a ticker', () => {
    const { links } = planMerge(working, importSet, board);
    expect(links.some((l) => l.importId === 'AAPL')).toBe(false);
  });
});

describe('applyMerge', () => {
  it('links ext:nvidia -> NVDA, collapsing onto the existing node', () => {
    const { graph, summary } = applyMerge(working, importSet, { 'ext:nvidia': 'NVDA', 'ext:foundry': 'ext:foundry' }, { dupPolicy: 'keep' });
    expect(graph.nodes).not.toContain('ext:nvidia');
    expect(graph.nodes).toContain('ext:foundry');
    expect(graph.node_meta?.['ext:nvidia']).toBeUndefined(); // ticker adopts board identity
    expect(summary.linked).toBe(1);
    // NVDA->foundry edge added (re-pointed from ext:nvidia); AAPL->NVDA partner is a duplicate
    expect(graph.edges.some((e) => e.source === 'NVDA' && e.target === 'ext:foundry')).toBe(true);
    expect(summary.duplicates).toBe(1);
  });
  it('keeps the existing edge by default on a duplicate', () => {
    const { graph } = applyMerge(working, importSet, { 'ext:nvidia': 'NVDA' }, { dupPolicy: 'keep' });
    const dup = graph.edges.find((e) => e.source === 'AAPL' && e.target === 'NVDA' && e.type === 'partner')!;
    expect(dup.sentiment).toBe('positive'); // mine kept (not the imported 'negative')
    expect(dup.evidence).toBe('news');
  });
  it('uses the imported edge when dupPolicy=import', () => {
    const { graph } = applyMerge(working, importSet, { 'ext:nvidia': 'NVDA' }, { dupPolicy: 'import' });
    const dup = graph.edges.find((e) => e.source === 'AAPL' && e.target === 'NVDA' && e.type === 'partner')!;
    expect(dup.sentiment).toBe('negative');
  });
  it('keeps native node_meta on a same-id ticker merge (no downgrade)', () => {
    const w2: KnowledgeGraph = { ...working, node_meta: { NVDA: { label: 'NVDA', kind: '', source: 'native' } } };
    const imp2: KnowledgeGraph = { ...importSet, nodes: ['NVDA'], node_meta: { NVDA: { label: 'Nvidia', kind: 'company', source: 'imported' } }, edges: [] };
    const { graph } = applyMerge(w2, imp2, {}, { dupPolicy: 'keep' });
    expect(graph.node_meta?.['NVDA']?.source).toBe('native');
  });
});
