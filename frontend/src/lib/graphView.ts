import type { GraphEdge, KnowledgeGraph, NetworkSignal, RelationType, ScreenBoard, StockScore } from '../types';

export type NodeDirection = 'buy' | 'sell' | 'hold' | 'unknown';

export interface ViewNode {
  id: string;            // ticker or external id
  label: string;         // ticker or node_meta label
  direction: NodeDirection;
  score: number;         // 0..100 (0 when off-board)
  sector: string;        // '' when off-board
  onBoard: boolean;
  external: boolean;     // imported / non-ticker node (rendered distinctly)
  kind: string;          // node_meta kind, '' for tickers
  network?: NetworkSignal | null;
}

export interface ViewLink {
  source: string;
  target: string;
  type: RelationType;
  sentiment: GraphEdge['sentiment'];
  weight: number;
  confidence: number;
  evidence: string;
  url: string;
  origin?: 'extracted' | 'imported' | 'manual';
}

export function mergeNodes(graph: KnowledgeGraph, board?: ScreenBoard | null): ViewNode[] {
  const byTicker = new Map(board?.items.map((s) => [s.ticker, s]) ?? []);
  const meta = graph.node_meta ?? {};
  return graph.nodes.map((id) => {
    const s = byTicker.get(id);
    const m = meta[id];
    return {
      id,
      label: m?.label || id,
      direction: (s?.direction ?? 'unknown') as NodeDirection,
      score: s?.score ?? 0,
      sector: s?.sector ?? '',
      onBoard: !!s,
      external: !s && (!!m || id.startsWith('ext:')),
      kind: m?.kind ?? '',
      network: s?.network ?? null,
    };
  });
}

export function toLinks(graph: KnowledgeGraph): ViewLink[] {
  return graph.edges.map((e) => ({
    source: e.source, target: e.target, type: e.type, sentiment: e.sentiment,
    weight: e.weight, confidence: e.confidence, evidence: e.evidence, url: e.url,
    origin: e.origin ?? 'extracted',
  }));
}

export function applyFilters(
  nodes: ViewNode[],
  links: ViewLink[],
  sector: string | null,
  enabledTypes: Set<RelationType>,
): { nodes: ViewNode[]; links: ViewLink[] } {
  const ns = sector ? nodes.filter((n) => n.sector === sector) : nodes;
  const keep = new Set(ns.map((n) => n.id));
  const ls = links.filter((l) => enabledTypes.has(l.type) && keep.has(l.source) && keep.has(l.target));
  return { nodes: ns, links: ls };
}

export function directionColor(d: NodeDirection): string {
  // hold mirrors --gold, the app-wide HOLD colour (badges/verdicts)
  return d === 'buy' ? '#3fb950' : d === 'sell' ? '#f85149' : d === 'hold' ? '#e8c87e' : '#484f58';
}

export function sentimentColor(s: ViewLink['sentiment']): string {
  return s === 'positive' ? '#3fb950' : s === 'negative' ? '#f85149' : '#6e7681';
}

export function nodeRadius(score: number): number {
  return 4 + (Math.max(0, Math.min(100, score)) / 100) * 8; // 4..12
}

const _SUFFIX = /\b(inc|corp|corporation|co|ltd|plc|company|companies|holdings|group|the|class)\b\.?/gi;

/** Normalise a company name for matching (modelled on the backend TickerResolver). */
export function normalizeName(s: string): string {
  return (s || '').toLowerCase().replace(_SUFFIX, '').replace(/[^a-z0-9 ]/g, '').replace(/\s+/g, ' ').trim();
}

function slug(s: string): string {
  return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

export interface ResolvedTarget { id: string; label: string; external: boolean; isNew: boolean }

/** Map a free-typed target to an existing node, a Discover ticker, a new ticker node, or a concept. */
export function resolveManualTarget(input: string, graph: KnowledgeGraph, board: StockScore[]): ResolvedTarget {
  const raw = input.trim();
  const meta = graph.node_meta ?? {};
  const has = (id: string) => graph.nodes.includes(id);

  const byId = graph.nodes.find((n) => n.toLowerCase() === raw.toLowerCase());
  if (byId) return { id: byId, label: meta[byId]?.label || byId, external: byId.startsWith('ext:') || byId.startsWith('man:'), isNew: false };

  const byLabel = graph.nodes.find((n) => normalizeName(meta[n]?.label || n) === normalizeName(raw));
  if (byLabel) return { id: byLabel, label: meta[byLabel]?.label || byLabel, external: byLabel.startsWith('ext:') || byLabel.startsWith('man:'), isNew: false };

  const sym = board.find((s) => s.ticker.toUpperCase() === raw.toUpperCase());
  if (sym) return { id: sym.ticker, label: sym.ticker, external: false, isNew: !has(sym.ticker) };
  const named = board.find((s) => normalizeName(s.name) === normalizeName(raw));
  if (named) return { id: named.ticker, label: named.ticker, external: false, isNew: !has(named.ticker) };

  if (raw.length <= 10 && raw === raw.toUpperCase() && /^[A-Z0-9.\-]+$/.test(raw) && /[A-Z]/.test(raw)) {
    return { id: raw, label: raw, external: false, isNew: !has(raw) };
  }
  const id = `man:${slug(raw)}`;
  return { id, label: raw, external: true, isNew: !has(id) };
}

export const COMPANY_TICKER_RE = /^[A-Za-z][A-Za-z0-9.\-]{0,9}$/;

/** Add a manual COMPANY node (id = upper-cased ticker, expandable + scoreable), unlike the
 *  `man:` concept nodes. No-op on invalid ticker or existing id. */
export function addCompanyNode(graph: KnowledgeGraph, c: { ticker: string; label?: string }): KnowledgeGraph {
  const id = c.ticker.trim().toUpperCase();
  if (!COMPANY_TICKER_RE.test(c.ticker.trim()) || graph.nodes.includes(id)) return graph;
  const node_meta = { ...(graph.node_meta ?? {}) };
  node_meta[id] = { label: (c.label ?? '').trim() || id, kind: 'company', source: 'manual' };
  return { ...graph, nodes: [...graph.nodes, id], node_meta };
}

/** Re-identify a node as the given ticker, rewriting its edges and meta — once the new id is a
 *  Discover-board ticker the view joins it to the board (direction/score). A same-id call only
 *  updates the display label (empty label falls back to the ticker). Returns null on a bad
 *  ticker, an unknown node, or when the ticker already names another node. */
export function renameNode(
  graph: KnowledgeGraph,
  oldId: string,
  c: { ticker: string; label?: string },
): { graph: KnowledgeGraph; id: string } | null {
  const id = c.ticker.trim().toUpperCase();
  if (!COMPANY_TICKER_RE.test(c.ticker.trim()) || !graph.nodes.includes(oldId)) return null;
  if (id !== oldId && graph.nodes.includes(id)) return null;
  const node_meta = { ...(graph.node_meta ?? {}) };
  const prev = node_meta[oldId];
  delete node_meta[oldId];
  node_meta[id] = { label: (c.label ?? '').trim() || id, kind: 'company', source: prev?.source ?? 'manual' };
  if (id === oldId) return { graph: { ...graph, node_meta }, id };
  return {
    graph: {
      ...graph,
      nodes: graph.nodes.map((n) => (n === oldId ? id : n)),
      edges: graph.edges.map((e) => ({
        ...e,
        source: e.source === oldId ? id : e.source,
        target: e.target === oldId ? id : e.target,
      })),
      node_meta,
    },
    id,
  };
}

/** Add a node; concept/external ids (`man:`/`ext:`) get a `manual`/existing meta entry. No-op if present. */
export function addManualNode(graph: KnowledgeGraph, meta: { id: string; label: string; kind?: string }): KnowledgeGraph {
  if (graph.nodes.includes(meta.id)) return graph;
  const node_meta = { ...(graph.node_meta ?? {}) };
  if (meta.id.startsWith('man:') || meta.id.startsWith('ext:')) {
    node_meta[meta.id] = { label: meta.label || meta.id, kind: meta.kind || 'concept', source: 'manual' };
  }
  return { ...graph, nodes: [...graph.nodes, meta.id], node_meta };
}

/** Append a manual edge, creating any missing endpoint nodes; de-dupes by source|target|type. */
export function addManualEdge(graph: KnowledgeGraph, edge: GraphEdge): KnowledgeGraph {
  let g = graph;
  for (const ep of [edge.source, edge.target]) {
    if (!g.nodes.includes(ep)) g = addManualNode(g, { id: ep, label: ep });
  }
  const key = `${edge.source}|${edge.target}|${edge.type}`;
  if (g.edges.some((e) => `${e.source}|${e.target}|${e.type}` === key)) return g;
  return { ...g, edges: [...g.edges, edge] };
}

export function deleteNode(graph: KnowledgeGraph, id: string): KnowledgeGraph {
  const node_meta = { ...(graph.node_meta ?? {}) };
  delete node_meta[id];
  return {
    ...graph,
    nodes: graph.nodes.filter((n) => n !== id),
    edges: graph.edges.filter((e) => e.source !== id && e.target !== id),
    node_meta,
  };
}

export function deleteEdge(graph: KnowledgeGraph, ref: { source: string; target: string; type: RelationType }): KnowledgeGraph {
  return {
    ...graph,
    edges: graph.edges.filter((e) => !(e.source === ref.source && e.target === ref.target && e.type === ref.type)),
  };
}

/** Accumulate an explored subgraph: union nodes, dedupe edges by source|target|type, union node_meta.
 *  Pure — used by the explorer to merge each one-hop fragment into the working graph. */
export function mergeGraph(into: KnowledgeGraph | null, fragment: KnowledgeGraph): KnowledgeGraph {
  if (!into) {
    return {
      ...fragment, nodes: [...fragment.nodes], edges: [...fragment.edges],
      node_meta: { ...(fragment.node_meta ?? {}) },
    };
  }
  const nodes = Array.from(new Set([...into.nodes, ...fragment.nodes]));
  const seen = new Set(into.edges.map((e) => `${e.source}|${e.target}|${e.type}`));
  const edges = [...into.edges];
  for (const e of fragment.edges) {
    const k = `${e.source}|${e.target}|${e.type}`;
    if (!seen.has(k)) { seen.add(k); edges.push(e); }
  }
  const node_meta = { ...(into.node_meta ?? {}), ...(fragment.node_meta ?? {}) };
  return { ...into, nodes, edges, node_meta };
}
