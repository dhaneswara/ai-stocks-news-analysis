import { describe, expect, it } from 'vitest';
import { exportFilename, toImportModel } from './graphExport';
import type { KnowledgeGraph } from '../types';

const GRAPH: KnowledgeGraph = {
  as_of: '2026-06-13', scope: 'active', built: 1, skipped: 0,
  nodes: ['NVDA', 'ext:acme', 'man:project-x'],
  edges: [
    {
      source: 'NVDA', target: 'ext:acme', type: 'supplier', sentiment: 'positive',
      weight: 0.8, confidence: 0.7, evidence: 'deal', url: 'http://x', as_of: '2026-06-01',
      origin: 'manual',
    },
  ],
  node_meta: {
    'ext:acme': { label: 'Acme Corp', kind: 'private_company', source: 'imported' },
    'man:project-x': { label: 'Project X', kind: 'product', source: 'manual' },
  },
};

describe('toImportModel', () => {
  it('maps node label/kind from node_meta, falling back to the id', () => {
    const m = toImportModel(GRAPH, 'Tech');
    expect(m.nodes).toContainEqual({ id: 'NVDA', label: 'NVDA', kind: '' });
    expect(m.nodes).toContainEqual({ id: 'ext:acme', label: 'Acme Corp', kind: 'private_company' });
    expect(m.nodes).toContainEqual({ id: 'man:project-x', label: 'Project X', kind: 'product' });
  });

  it('projects edges to the import shape, dropping origin and per-edge as_of', () => {
    const m = toImportModel(GRAPH, 'Tech');
    expect(m.edges).toEqual([
      {
        source: 'NVDA', target: 'ext:acme', type: 'supplier', sentiment: 'positive',
        weight: 0.8, confidence: 0.7, evidence: 'deal', url: 'http://x',
      },
    ]);
    expect(m.edges[0]).not.toHaveProperty('origin');
    expect(m.edges[0]).not.toHaveProperty('as_of');
  });

  it('passes name through and takes as_of from the graph', () => {
    const m = toImportModel(GRAPH, 'Tech');
    expect(m.name).toBe('Tech');
    expect(m.as_of).toBe('2026-06-13');
  });

  it('handles a graph with no node_meta and an empty graph', () => {
    const bare: KnowledgeGraph = {
      as_of: '', scope: 'active', built: 0, skipped: 0, nodes: ['AAPL'], edges: [],
    };
    expect(toImportModel(bare, '').nodes).toEqual([{ id: 'AAPL', label: 'AAPL', kind: '' }]);
    const empty: KnowledgeGraph = { as_of: '', scope: 'active', built: 0, skipped: 0, nodes: [], edges: [] };
    const m = toImportModel(empty, '');
    expect(m.nodes).toEqual([]);
    expect(m.edges).toEqual([]);
    expect(m.as_of).toBe('');
  });
});

describe('exportFilename', () => {
  it('slugs the name and appends .json', () => {
    expect(exportFilename('My Tech Graph!')).toBe('my-tech-graph.json');
  });
  it('falls back to graph.json for empty or punctuation-only names', () => {
    expect(exportFilename('')).toBe('graph.json');
    expect(exportFilename('  ---  ')).toBe('graph.json');
  });
});
