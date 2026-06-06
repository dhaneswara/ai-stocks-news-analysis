import type { GraphEdge, KnowledgeGraph, NetworkSignal, RelationType, ScreenBoard } from '../types';

export type NodeDirection = 'buy' | 'sell' | 'hold' | 'unknown';

export interface ViewNode {
  id: string;            // ticker
  label: string;         // ticker
  direction: NodeDirection;
  score: number;         // 0..100 (0 when off-board)
  sector: string;        // '' when off-board
  onBoard: boolean;
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
}

export function mergeNodes(graph: KnowledgeGraph, board?: ScreenBoard | null): ViewNode[] {
  const byTicker = new Map(board?.items.map((s) => [s.ticker, s]) ?? []);
  return graph.nodes.map((ticker) => {
    const s = byTicker.get(ticker);
    return {
      id: ticker,
      label: ticker,
      direction: (s?.direction ?? 'unknown') as NodeDirection,
      score: s?.score ?? 0,
      sector: s?.sector ?? '',
      onBoard: !!s,
      network: s?.network ?? null,
    };
  });
}

export function toLinks(graph: KnowledgeGraph): ViewLink[] {
  return graph.edges.map((e) => ({
    source: e.source, target: e.target, type: e.type, sentiment: e.sentiment,
    weight: e.weight, confidence: e.confidence, evidence: e.evidence, url: e.url,
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
