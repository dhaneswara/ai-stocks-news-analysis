import { useState } from 'react';
import { searchNodes, type ViewNode } from '../lib/graphView';

/** Find-a-node box overlaid on the canvas: matches ticker or company name; picking a
 *  match hands the id to the canvas, which selects and centres on the node. */
export function GraphSearch({ nodes, onPick }: { nodes: ViewNode[]; onPick: (id: string) => void }) {
  const [q, setQ] = useState('');
  const matches = searchNodes(nodes, q);
  const pick = (id: string) => { onPick(id); setQ(''); };
  return (
    <div className="graph-search">
      <input
        placeholder="Find ticker / company…" aria-label="find node" value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && matches.length) pick(matches[0].id);
          if (e.key === 'Escape') setQ('');
        }}
      />
      {q.trim() !== '' && (
        matches.length ? (
          <ul className="graph-search-results">
            {matches.map((m) => (
              <li key={m.id}>
                <button type="button" onClick={() => pick(m.id)}>
                  <b>{m.label}</b>{m.label !== m.id && <span className="muted"> {m.id}</span>}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No matches.</p>
        )
      )}
    </div>
  );
}
