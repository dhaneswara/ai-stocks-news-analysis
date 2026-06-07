import type { GraphEdge, KnowledgeGraph, NodeMeta, StockScore } from '../types';
import { normalizeName } from './graphView';

export interface MergeLinkRow {
  importId: string;          // import-set node id, e.g. 'ext:nvidia' or 'NVDA'
  label: string;             // display label
  external: boolean;         // ext:/man: or has imported node_meta
  suggestion: string | null; // suggested ticker (Discover/working match) or null
  resolved: string;          // default choice: a ticker id, or importId to keep-as-is
}

export interface MergeSummary {
  addedNodes: number;
  addedEdges: number;
  duplicates: number; // (source,target,type) present in both
  linked: number;     // import nodes re-pointed to a ticker
  merged: number;     // import tickers already present in working
}

export type DupPolicy = 'keep' | 'import';

const isExt = (id: string) => id.startsWith('ext:') || id.startsWith('man:');

/** Build the editable link rows: one per external import node, with a suggested Discover ticker. */
export function planMerge(working: KnowledgeGraph, importSet: KnowledgeGraph, board: StockScore[]): { links: MergeLinkRow[] } {
  const byTicker = new Set(board.map((s) => s.ticker.toUpperCase()));
  const byName = new Map(board.map((s) => [normalizeName(s.name), s.ticker]));
  const wmeta = working.node_meta ?? {};
  const workingByName = new Map(working.nodes.map((id) => [normalizeName(wmeta[id]?.label || id), id]));
  const meta = importSet.node_meta ?? {};

  const links: MergeLinkRow[] = [];
  for (const id of importSet.nodes) {
    if (!(isExt(id) || meta[id])) continue; // already a ticker -> merges/adds directly
    const label = meta[id]?.label || id;
    const norm = normalizeName(label);
    let suggestion: string | null = null;
    if (byName.has(norm)) suggestion = byName.get(norm)!;
    else if (byTicker.has(label.toUpperCase())) suggestion = label.toUpperCase();
    else if (workingByName.has(norm)) suggestion = workingByName.get(norm)!;
    links.push({ importId: id, label, external: true, suggestion, resolved: suggestion ?? id });
  }
  return { links };
}

/** Apply the resolved link choices + duplicate policy; pure, used for live counts and the final commit. */
export function applyMerge(
  working: KnowledgeGraph, importSet: KnowledgeGraph,
  resolved: Record<string, string>, opts: { dupPolicy: DupPolicy },
): { graph: KnowledgeGraph; summary: MergeSummary } {
  const map = (id: string) => resolved[id] ?? id;

  // 1) rewrite import nodes / meta / edges through the link map
  const importNodes = new Set<string>(importSet.nodes.map(map));
  const importMeta: Record<string, NodeMeta> = {};
  for (const [k, v] of Object.entries(importSet.node_meta ?? {})) {
    const nk = map(k);
    if (isExt(nk)) importMeta[nk] = v; // keep meta only for nodes that stay external
  }
  const rewritten: GraphEdge[] = [];
  const seen = new Set<string>();
  for (const e of importSet.edges) {
    const s = map(e.source); const t = map(e.target);
    if (s === t) continue;
    const key = `${s}|${t}|${e.type}`;
    if (seen.has(key)) continue;
    seen.add(key);
    rewritten.push({ ...e, source: s, target: t });
  }

  // 2) union into working
  const nodeSet = new Set(working.nodes);
  const nodes = [...working.nodes];
  let addedNodes = 0;
  for (const n of importNodes) if (!nodeSet.has(n)) { nodes.push(n); nodeSet.add(n); addedNodes++; }

  const node_meta = { ...importMeta, ...(working.node_meta ?? {}) }; // working wins -> ticker keeps identity

  const idx = new Map<string, number>();
  working.edges.forEach((e, i) => idx.set(`${e.source}|${e.target}|${e.type}`, i));
  const edges = [...working.edges];
  let addedEdges = 0; let duplicates = 0;
  for (const e of rewritten) {
    const key = `${e.source}|${e.target}|${e.type}`;
    if (idx.has(key)) {
      duplicates++;
      if (opts.dupPolicy === 'import') edges[idx.get(key)!] = e;
    } else {
      idx.set(key, edges.length);
      edges.push(e);
      addedEdges++;
    }
  }

  let linked = 0; let merged = 0;
  for (const id of importSet.nodes) {
    const r = map(id);
    if (r !== id && !isExt(r)) linked++;
    else if (r === id && !isExt(id) && working.nodes.includes(id)) merged++;
  }

  return { graph: { ...working, nodes, edges, node_meta }, summary: { addedNodes, addedEdges, duplicates, linked, merged } };
}
