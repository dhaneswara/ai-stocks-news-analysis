/** Serialize the working graph into the import-model JSON shape `normalize_import` accepts.
 *  Lossy by design (see the spec): origin and per-edge as_of are dropped; tickers are
 *  re-resolved on import. The file round-trips through the existing Import tab's file upload. */
import type { EdgeSentiment, KnowledgeGraph, RelationType } from '../types';

export interface ImportModelNode {
  id: string;
  label: string;
  kind: string;
}

export interface ImportModelEdge {
  source: string;
  target: string;
  type: RelationType;
  sentiment: EdgeSentiment;
  weight: number;
  confidence: number;
  evidence: string;
  url: string;
}

export interface ImportModel {
  name: string;
  as_of: string;
  nodes: ImportModelNode[];
  edges: ImportModelEdge[];
}

export function toImportModel(graph: KnowledgeGraph, name: string): ImportModel {
  const meta = graph.node_meta ?? {};
  return {
    name,
    as_of: graph.as_of ?? '',
    nodes: graph.nodes.map((id) => ({
      id,
      label: meta[id]?.label || id, // empty/missing label -> the id is the useful display value
      kind: meta[id]?.kind || '',
    })),
    edges: graph.edges.map((e) => ({
      source: e.source,
      target: e.target,
      type: e.type,
      sentiment: e.sentiment,
      weight: e.weight,
      confidence: e.confidence,
      evidence: e.evidence,
      url: e.url,
    })),
  };
}

export function exportFilename(name: string): string {
  const slug = (name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return `${slug || 'graph'}.json`;
}
