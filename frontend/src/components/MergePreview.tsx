import { useMemo, useState } from 'react';
import type { KnowledgeGraph, StockScore } from '../types';
import { applyMerge, planMerge, type DupPolicy } from '../lib/graphMerge';

export interface MergePreviewProps {
  working: KnowledgeGraph;
  importSet: KnowledgeGraph;
  board: StockScore[];
  onApply: (merged: KnowledgeGraph) => void;
  onCancel: () => void;
}

/**
 * Preview the merge of one import set. NOTE: `resolved` is seeded once from the initial plan,
 * so the parent must pass a stable `key` tied to the import-set identity to force a remount
 * (and re-seed) whenever the import set changes.
 */
export function MergePreview({ working, importSet, board, onApply, onCancel }: MergePreviewProps) {
  const plan = useMemo(() => planMerge(working, importSet, board), [working, importSet, board]);
  const [resolved, setResolved] = useState<Record<string, string>>(
    () => Object.fromEntries(plan.links.map((l) => [l.importId, l.resolved])),
  );
  const [dupPolicy, setDupPolicy] = useState<DupPolicy>('keep');
  const tickers = useMemo(() => [...board].sort((a, b) => a.ticker.localeCompare(b.ticker)), [board]);

  const { graph, summary } = useMemo(
    () => applyMerge(working, importSet, resolved, { dupPolicy }),
    [working, importSet, resolved, dupPolicy],
  );

  return (
    <div className="merge-preview">
      <h4>Merge into graph</h4>
      {plan.links.length > 0 ? (
        <div className="merge-links">
          <span className="label">Link imported companies</span>
          {plan.links.map((l) => (
            <label key={l.importId} className="merge-link-row">
              <span className="merge-link-label">{l.label}</span>
              <select value={resolved[l.importId]} onChange={(e) => setResolved((r) => ({ ...r, [l.importId]: e.target.value }))}>
                <option value={l.importId}>keep as external</option>
                {tickers.map((s) => (
                  <option key={s.ticker} value={s.ticker}>{s.ticker} — {s.name}</option>
                ))}
              </select>
            </label>
          ))}
        </div>
      ) : (
        <p className="muted">No external companies to link.</p>
      )}

      <label className="merge-duppolicy">
        Duplicate relationships:{' '}
        <select value={dupPolicy} onChange={(e) => setDupPolicy(e.target.value as DupPolicy)}>
          <option value="keep">keep mine</option>
          <option value="import">use imported</option>
        </select>
      </label>

      <p className="muted merge-summary">
        +{summary.addedNodes} nodes, +{summary.addedEdges} edges · {summary.linked} linked ·{' '}
        {summary.merged} already in graph · {summary.duplicates} duplicate{summary.duplicates === 1 ? '' : 's'}
      </p>

      <div className="graph-actions">
        <button onClick={() => onApply(graph)}>Apply merge</button>
        <button className="secondary" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
