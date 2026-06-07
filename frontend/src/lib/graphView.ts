import type { GraphEdge, KnowledgeGraph, NetworkSignal, RelationType, ScreenBoard } from '../types';

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
  origin?: 'extracted' | 'imported';
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
  return d === 'buy' ? '#3fb950' : d === 'sell' ? '#f85149' : d === 'hold' ? '#8b949e' : '#484f58';
}

export function sentimentColor(s: ViewLink['sentiment']): string {
  return s === 'positive' ? '#3fb950' : s === 'negative' ? '#f85149' : '#6e7681';
}

export function nodeRadius(score: number): number {
  return 4 + (Math.max(0, Math.min(100, score)) / 100) * 8; // 4..12
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
