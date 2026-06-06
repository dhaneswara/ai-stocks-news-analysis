import { Link } from 'react-router-dom';
import type { RelationType } from '../types';
import type { ViewNode } from '../lib/graphView';

const EDGE_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary'];

export interface GraphSidebarProps {
  asOf: string;
  built: number;
  skipped: number;
  nodeCount: number;
  linkCount: number;
  sectors: string[];
  sector: string;
  onSector: (s: string) => void;
  enabledTypes: Set<RelationType>;
  onToggleType: (t: RelationType) => void;
  selected: ViewNode | null;
  onRebuild: () => void;
  rebuilding: boolean;
  rebuildError?: string | null;
}

export function GraphSidebar(props: GraphSidebarProps) {
  const { asOf, built, skipped, nodeCount, linkCount, sectors, sector, onSector,
    enabledTypes, onToggleType, selected, onRebuild, rebuilding, rebuildError } = props;
  return (
    <aside className="graph-sidebar panel">
      <div className="panel-head"><span className="section-label">Knowledge graph</span></div>

      <button onClick={onRebuild} disabled={rebuilding}>
        {rebuilding ? 'Rebuilding… (LLM)' : 'Rebuild graph'}
      </button>
      {rebuildError && <p className="error">Rebuild failed: {rebuildError}</p>}
      <p className="muted">
        {asOf ? `As of ${new Date(asOf).toLocaleString()}` : 'Not built yet'}
        {built ? ` · ${built} built` : ''}{skipped ? `, ${skipped} skipped` : ''}
      </p>
      <p className="muted">{nodeCount} nodes · {linkCount} edges shown</p>

      <label>Sector
        <select value={sector} onChange={(e) => onSector(e.target.value)}>
          <option value="">All sectors</option>
          {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>

      <div className="graph-types">
        {EDGE_TYPES.map((t) => (
          <label key={t} className="chip-toggle">
            <input type="checkbox" checked={enabledTypes.has(t)} onChange={() => onToggleType(t)} /> {t}
          </label>
        ))}
      </div>

      {selected ? (
        <div className="graph-detail">
          <h4>{selected.label}{' '}
            <span className={`badge ${selected.direction === 'unknown' ? 'hold' : selected.direction}`}>
              {selected.direction.toUpperCase()}
            </span>
          </h4>
          {selected.onBoard && <p className="muted">score {selected.score.toFixed(0)}</p>}
          {selected.network && selected.network.influences.length > 0 ? (
            <ul className="factor-list">
              {selected.network.influences.map((inf, i) => {
                const lean = inf.signed > 0 ? 'bullish' : inf.signed < 0 ? 'bearish' : 'neutral';
                return (
                  <li key={i}>
                    <b>{inf.type} {inf.neighbour}</b> — news {inf.edge_sentiment} ({lean})
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="muted">No outgoing network edges.</p>
          )}
          <Link to={`/?ticker=${encodeURIComponent(selected.id)}`}>Open in Dashboard →</Link>
        </div>
      ) : (
        <div className="graph-legend">
          <p className="muted">Click a node for its network detail.</p>
          <p className="label">
            <span style={{ color: '#3fb950' }}>●</span> buy{' '}
            <span style={{ color: '#f85149' }}>●</span> sell{' '}
            <span style={{ color: '#8b949e' }}>●</span> hold · edge colour = news effect
          </p>
        </div>
      )}
    </aside>
  );
}
