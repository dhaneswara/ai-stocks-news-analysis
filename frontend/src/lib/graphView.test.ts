import { describe, expect, it } from 'vitest';
import { applyFilters, directionColor, mergeNodes, nodeRadius, sentimentColor, toLinks } from './graphView';
import type { KnowledgeGraph, ScreenBoard, RelationType } from '../types';

const GRAPH: KnowledgeGraph = {
  as_of: 't', scope: 'focus', built: 1, skipped: 0,
  nodes: ['AAPL', 'TSM', 'XYZ'],
  edges: [
    { source: 'AAPL', target: 'TSM', type: 'supplier', sentiment: 'negative', weight: 1, confidence: 1, evidence: 'e', url: '', as_of: '' },
    { source: 'AAPL', target: 'XYZ', type: 'competitor', sentiment: 'positive', weight: 0.5, confidence: 0.8, evidence: '', url: '', as_of: '' },
  ],
};
const BOARD: ScreenBoard = {
  as_of: 't', scope: 'all', scanned: 2, skipped: 0,
  items: [
    { ticker: 'AAPL', name: 'Apple', sector: 'Tech', price: 1, change_pct: 0, score: 80, direction: 'sell', reasons: [], components: {}, as_of: '', net: -0.3 },
    { ticker: 'TSM', name: 'Taiwan Semi', sector: 'Tech', price: 1, change_pct: 0, score: 40, direction: 'sell', reasons: [], components: {}, as_of: '', net: -0.9 },
  ],
};

describe('mergeNodes', () => {
  it('joins board scores and marks off-board nodes unknown', () => {
    const nodes = mergeNodes(GRAPH, BOARD);
    const aapl = nodes.find((n) => n.id === 'AAPL')!;
    expect(aapl.direction).toBe('sell');
    expect(aapl.score).toBe(80);
    expect(aapl.onBoard).toBe(true);
    const xyz = nodes.find((n) => n.id === 'XYZ')!;
    expect(xyz.direction).toBe('unknown');
    expect(xyz.onBoard).toBe(false);
    expect(xyz.score).toBe(0);
  });
  it('handles a missing board', () => {
    expect(mergeNodes(GRAPH, null).every((n) => !n.onBoard)).toBe(true);
  });
});

describe('applyFilters', () => {
  it('filters by sector and drops orphaned links', () => {
    const nodes = mergeNodes(GRAPH, BOARD);
    const links = toLinks(GRAPH);
    const all: Set<RelationType> = new Set(['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary']);
    const out = applyFilters(nodes, links, 'Tech', all);
    expect(out.nodes.map((n) => n.id).sort()).toEqual(['AAPL', 'TSM']); // XYZ has no sector
    expect(out.links).toHaveLength(1); // AAPL->XYZ dropped (XYZ filtered out)
    expect(out.links[0].target).toBe('TSM');
  });
  it('filters by edge type', () => {
    const nodes = mergeNodes(GRAPH, BOARD);
    const links = toLinks(GRAPH);
    const out = applyFilters(nodes, links, null, new Set(['competitor'] as RelationType[]));
    expect(out.links.map((l) => l.type)).toEqual(['competitor']);
  });
});

describe('encoders', () => {
  it('maps colours and radius', () => {
    expect(directionColor('buy')).toBe('#3fb950');
    expect(directionColor('unknown')).toBe('#484f58');
    expect(sentimentColor('negative')).toBe('#f85149');
    expect(nodeRadius(0)).toBeLessThan(nodeRadius(100));
  });
});
