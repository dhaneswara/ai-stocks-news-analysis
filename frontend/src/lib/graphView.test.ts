import { describe, expect, it } from 'vitest';
import { applyFilters, directionColor, mergeGraph, mergeNodes, nodeRadius, searchNodes, sentimentColor, toLinks, type ViewNode } from './graphView';
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
    expect(directionColor('hold')).toBe('#e8c87e');
    expect(directionColor('hold')).not.toBe(directionColor('unknown'));
    expect(directionColor('unknown')).toBe('#484f58');
    expect(sentimentColor('negative')).toBe('#f85149');
    expect(nodeRadius(0)).toBeLessThan(nodeRadius(100));
  });
});

const vn = (id: string, label = id): ViewNode => ({
  id, label, direction: 'unknown', score: 0, sector: '', onBoard: false, external: false, kind: '',
});

describe('searchNodes', () => {
  const NODES = [vn('TSM', 'TSMC'), vn('AAPL', 'Apple'), vn('MSFT', 'Microsoft'), vn('ext:applied', 'Applied Materials')];

  it('matches ticker or name, id-prefix hits ranked before name hits', () => {
    expect(searchNodes(NODES, 'tsm').map((n) => n.id)).toEqual(['TSM']);          // exact ticker
    expect(searchNodes(NODES, 'a').map((n) => n.id)).toEqual(['AAPL', 'ext:applied']); // id prefix > label prefix
    expect(searchNodes(NODES, 'app').map((n) => n.id)).toEqual(['AAPL', 'ext:applied']); // label prefixes, tie by label
    expect(searchNodes(NODES, 'soft').map((n) => n.id)).toEqual(['MSFT']);        // label substring
  });

  it('is case-insensitive and empty for a blank query', () => {
    expect(searchNodes(NODES, 'APPLE').map((n) => n.id)).toEqual(['AAPL']);
    expect(searchNodes(NODES, '   ')).toEqual([]);
  });

  it('caps results at the limit', () => {
    const many = Array.from({ length: 12 }, (_, i) => vn(`T${i}`));
    expect(searchNodes(many, 't')).toHaveLength(8);
  });
});

describe('mergeGraph', () => {
  const FRAG_A: KnowledgeGraph = {
    as_of: 't', scope: 'company:AAPL', built: 1, skipped: 0, nodes: ['AAPL', 'TSM'],
    edges: [{ source: 'AAPL', target: 'TSM', type: 'supplier', sentiment: 'negative', weight: 1, confidence: 1, evidence: '', url: '', as_of: '' }],
  };
  const FRAG_B: KnowledgeGraph = {
    as_of: 't', scope: 'company:TSM', built: 1, skipped: 0, nodes: ['TSM', 'FOO'],
    edges: [
      { source: 'AAPL', target: 'TSM', type: 'supplier', sentiment: 'negative', weight: 1, confidence: 1, evidence: '', url: '', as_of: '' },
      { source: 'TSM', target: 'FOO', type: 'customer', sentiment: 'positive', weight: 1, confidence: 1, evidence: '', url: '', as_of: '' },
    ],
  };

  it('returns the fragment when there is no prior graph', () => {
    const out = mergeGraph(null, FRAG_A);
    expect(out.nodes).toEqual(['AAPL', 'TSM']);
    expect(out.edges).toHaveLength(1);
  });

  it('unions nodes and dedupes edges by source|target|type', () => {
    const out = mergeGraph(FRAG_A, FRAG_B);
    expect(out.nodes.sort()).toEqual(['AAPL', 'FOO', 'TSM']);
    expect(out.edges).toHaveLength(2); // AAPL->TSM kept once, TSM->FOO added
    expect(out.edges.some((e) => e.target === 'FOO')).toBe(true);
  });
});

import {
  addCompanyNode, addManualEdge, addManualNode, deleteEdge, deleteNode, normalizeName, renameNode, resolveManualTarget,
} from './graphView';
import type { GraphEdge } from '../types';

const EMPTY = (): KnowledgeGraph => ({ as_of: '', scope: 'x', built: 0, skipped: 0, nodes: [], edges: [], node_meta: {} });

describe('normalizeName', () => {
  it('strips suffixes and punctuation', () => {
    expect(normalizeName('NVIDIA Corporation')).toBe('nvidia');
    expect(normalizeName('Alphabet Inc. (Class A)')).toBe('alphabet a'); // "class" stripped, "a" kept
    expect(normalizeName('Apple')).toBe('apple');
  });
});

describe('resolveManualTarget', () => {
  const board = BOARD.items; // AAPL/Apple, TSM/Taiwan Semi
  it('reuses an existing node by id (case-insensitive)', () => {
    const g = { ...EMPTY(), nodes: ['AAPL'] };
    expect(resolveManualTarget('aapl', g, board)).toMatchObject({ id: 'AAPL', isNew: false });
  });
  it('links a Discover company by name', () => {
    expect(resolveManualTarget('Taiwan Semi', EMPTY(), board)).toMatchObject({ id: 'TSM', external: false, isNew: true });
  });
  it('links a Discover company by symbol', () => {
    expect(resolveManualTarget('TSM', EMPTY(), board)).toMatchObject({ id: 'TSM', external: false });
  });
  it('makes a ticker node for an unknown ALL-CAPS symbol', () => {
    expect(resolveManualTarget('ASML', EMPTY(), board)).toMatchObject({ id: 'ASML', external: false, isNew: true });
  });
  it('makes a concept node for free text', () => {
    expect(resolveManualTarget('AI chip demand', EMPTY(), board)).toMatchObject({ id: 'man:ai-chip-demand', external: true });
  });
  it('reuses an existing node by its node_meta label', () => {
    const g = { ...EMPTY(), nodes: ['ext:openai'],
      node_meta: { 'ext:openai': { label: 'OpenAI Inc.', kind: 'private_company', source: 'imported' as const } } };
    expect(resolveManualTarget('openai', g, [])).toMatchObject({ id: 'ext:openai', external: true, isNew: false });
  });
});

describe('manual graph mutations', () => {
  const edge = (s: string, t: string, type: RelationType = 'partner'): GraphEdge => ({
    source: s, target: t, type, sentiment: 'positive', weight: 0.5, confidence: 0.9, evidence: '', url: '', as_of: '', origin: 'manual',
  });
  it('addManualEdge appends and creates missing endpoints', () => {
    const out = addManualEdge({ ...EMPTY(), nodes: ['AAPL'] }, edge('AAPL', 'man:x'));
    expect(out.nodes).toContain('man:x');
    expect(out.edges[0].origin).toBe('manual');
    expect(out.node_meta?.['man:x']?.source).toBe('manual');
  });
  it('addManualEdge de-dupes by source|target|type', () => {
    let g = addManualEdge({ ...EMPTY(), nodes: ['AAPL', 'TSM'] }, edge('AAPL', 'TSM'));
    g = addManualEdge(g, edge('AAPL', 'TSM'));
    expect(g.edges).toHaveLength(1);
  });
  it('addManualNode adds a man: concept with meta', () => {
    const out = addManualNode(EMPTY(), { id: 'man:x', label: 'X thing' });
    expect(out.node_meta?.['man:x']).toMatchObject({ label: 'X thing', source: 'manual' });
  });
  it('deleteNode removes the node, its meta, and incident edges', () => {
    let g = addManualEdge({ ...EMPTY(), nodes: ['AAPL'] }, edge('AAPL', 'man:x'));
    g = deleteNode(g, 'man:x');
    expect(g.nodes).not.toContain('man:x');
    expect(g.edges).toHaveLength(0);
    expect(g.node_meta?.['man:x']).toBeUndefined();
  });
  it('deleteEdge removes only the matching edge', () => {
    let g = addManualEdge({ ...EMPTY(), nodes: ['AAPL', 'TSM'] }, edge('AAPL', 'TSM', 'partner'));
    g = addManualEdge(g, edge('AAPL', 'TSM', 'supplier'));
    g = deleteEdge(g, { source: 'AAPL', target: 'TSM', type: 'partner' });
    expect(g.edges).toHaveLength(1);
    expect(g.edges[0].type).toBe('supplier');
  });
  it('addManualNode is a no-op when the node already exists', () => {
    const g = addManualNode(EMPTY(), { id: 'man:x', label: 'X' });
    expect(addManualNode(g, { id: 'man:x', label: 'X again' })).toBe(g);
  });
});

describe('addCompanyNode', () => {
  it('adds an upper-cased ticker node with company meta', () => {
    const g = addCompanyNode({ as_of: '', scope: 'explore', nodes: [], edges: [], built: 0, skipped: 0 },
      { ticker: 'tsm', label: 'TSMC' });
    expect(g.nodes).toEqual(['TSM']);
    expect(g.node_meta?.TSM).toEqual({ label: 'TSMC', kind: 'company', source: 'manual' });
  });

  it('rejects bad tickers and duplicates', () => {
    const base = { as_of: '', scope: 'explore', nodes: ['TSM'], edges: [], built: 0, skipped: 0 };
    expect(addCompanyNode(base, { ticker: 'not a ticker!!' })).toBe(base);
    expect(addCompanyNode(base, { ticker: 'TSM' })).toBe(base);
    expect(addCompanyNode(base, { ticker: 'tsm' })).toBe(base);   // case-insensitive duplicate
  });
});

describe('renameNode', () => {
  const G: KnowledgeGraph = {
    as_of: 't', scope: 'explore', built: 0, skipped: 0,
    nodes: ['ext:tsmc', 'AAPL'],
    edges: [{ source: 'AAPL', target: 'ext:tsmc', type: 'supplier', sentiment: 'negative', weight: 1, confidence: 1, evidence: '', url: '', as_of: '' }],
    node_meta: { 'ext:tsmc': { label: 'TSMC', kind: 'private_company', source: 'imported' } },
  };

  it('re-identifies a node, rewriting edges and meta (provenance kept)', () => {
    const res = renameNode(G, 'ext:tsmc', { ticker: 'tsm', label: 'TSMC' });
    expect(res?.id).toBe('TSM');
    expect(res?.graph.nodes).toEqual(['TSM', 'AAPL']);
    expect(res?.graph.edges[0].target).toBe('TSM');
    expect(res?.graph.node_meta?.TSM).toEqual({ label: 'TSMC', kind: 'company', source: 'imported' });
    expect(res?.graph.node_meta?.['ext:tsmc']).toBeUndefined();
  });

  it('a same-id call only updates the label; empty label falls back to the ticker', () => {
    const res = renameNode(G, 'AAPL', { ticker: 'AAPL', label: 'Apple Inc' });
    expect(res?.graph.nodes).toEqual(G.nodes);
    expect(res?.graph.edges).toBe(G.edges);
    expect(res?.graph.node_meta?.AAPL).toEqual({ label: 'Apple Inc', kind: 'company', source: 'manual' });
    const cleared = renameNode(res!.graph, 'AAPL', { ticker: 'aapl' });
    expect(cleared?.graph.node_meta?.AAPL?.label).toBe('AAPL');
  });

  it('returns null on collisions, bad tickers and unknown nodes', () => {
    expect(renameNode(G, 'ext:tsmc', { ticker: 'AAPL' })).toBeNull();   // would collide
    expect(renameNode(G, 'ext:tsmc', { ticker: 'not a ticker!!' })).toBeNull();
    expect(renameNode(G, 'GONE', { ticker: 'TSM' })).toBeNull();
  });
});

describe('imported nodes + meta', () => {
  const IMPORTED: KnowledgeGraph = {
    as_of: 't', scope: 'imported', built: 1, skipped: 0,
    nodes: ['AAPL', 'ext:openai'],
    node_meta: { 'ext:openai': { label: 'OpenAI', kind: 'private_company', source: 'imported' } },
    edges: [
      { source: 'AAPL', target: 'ext:openai', type: 'other', sentiment: 'positive',
        weight: 1, confidence: 1, evidence: '', url: '', as_of: '', origin: 'imported' },
    ],
  };

  it('marks ext/meta nodes external with their label', () => {
    const nodes = mergeNodes(IMPORTED, BOARD);
    const ext = nodes.find((n) => n.id === 'ext:openai')!;
    expect(ext.external).toBe(true);
    expect(ext.label).toBe('OpenAI');
    expect(ext.onBoard).toBe(false);
    const aapl = nodes.find((n) => n.id === 'AAPL')!;
    expect(aapl.external).toBe(false); // on the board -> not external
  });

  it('carries edge origin onto links', () => {
    expect(toLinks(IMPORTED)[0].origin).toBe('imported');
  });

  it('mergeGraph unions node_meta', () => {
    const out = mergeGraph(
      { as_of: 't', scope: 'x', built: 0, skipped: 0, nodes: ['AAPL'], edges: [] },
      IMPORTED,
    );
    expect(out.node_meta?.['ext:openai']?.label).toBe('OpenAI');
  });
});
