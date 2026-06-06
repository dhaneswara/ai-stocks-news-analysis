import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { RelationType, SavedGraphSummary } from '../types';
import type { ViewNode } from '../lib/graphView';

const EDGE_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary'];

export interface GraphSidebarProps {
  tab: 'explore' | 'saved';
  onTab: (t: 'explore' | 'saved') => void;
  onLoadRoot: (ticker: string) => void;
  onExpand: (ticker: string) => void;
  onSave: () => void;
  onClear: () => void;
  canSave: boolean;
  saving: boolean;
  loading: boolean;
  saved: SavedGraphSummary[];
  onLoadSaved: (root: string, version?: string) => void;
  onDeleteSaved: (root: string, version?: string) => void;
  nodeCount: number;
  linkCount: number;
  enabledTypes: Set<RelationType>;
  onToggleType: (t: RelationType) => void;
  selected: ViewNode | null;
}

export function GraphSidebar(props: GraphSidebarProps) {
  const {
    tab, onTab, onLoadRoot, onExpand, onSave, onClear, canSave, saving, loading,
    saved, onLoadSaved, onDeleteSaved, nodeCount, linkCount, enabledTypes, onToggleType, selected,
  } = props;
  const [rootInput, setRootInput] = useState('');

  return (
    <aside className="graph-sidebar panel">
      <div className="graph-tabs">
        <button type="button" className={`tab${tab === 'explore' ? ' active' : ''}`} onClick={() => onTab('explore')}>
          Explore
        </button>
        <button type="button" className={`tab${tab === 'saved' ? ' active' : ''}`} onClick={() => onTab('saved')}>
          Saved{saved.length ? ` (${saved.length})` : ''}
        </button>
      </div>

      {tab === 'explore' ? (
        <div className="graph-tab">
          <label>Start from a company
            <input
              placeholder="Ticker (e.g. AAPL)"
              value={rootInput}
              onChange={(e) => setRootInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && rootInput.trim()) onLoadRoot(rootInput.trim()); }}
            />
          </label>
          <button disabled={loading || !rootInput.trim()} onClick={() => onLoadRoot(rootInput.trim())}>Start</button>

          <div className="graph-section">
            <p className="muted">{nodeCount} nodes · {linkCount} edges</p>
            <div className="graph-actions">
              <button disabled={!canSave || saving} onClick={onSave}>{saving ? 'Saving…' : 'Save'}</button>
              <button className="secondary" disabled={!canSave} onClick={onClear}>Clear</button>
            </div>
          </div>

          <div className="graph-section">
            <span className="label">Show edge types</span>
            <div className="graph-types">
              {EDGE_TYPES.map((t) => (
                <label key={t} className="chip-toggle">
                  <input type="checkbox" checked={enabledTypes.has(t)} onChange={() => onToggleType(t)} /> {t}
                </label>
              ))}
            </div>
          </div>

          {selected ? (
            <div className="graph-detail">
              <h4>{selected.label}{' '}
                <span className={`badge ${selected.direction === 'unknown' ? 'hold' : selected.direction}`}>
                  {selected.direction.toUpperCase()}
                </span>
              </h4>
              {selected.onBoard && <p className="muted">score {selected.score.toFixed(0)}</p>}
              <button disabled={loading} onClick={() => onExpand(selected.id)}>Expand neighbours</button>
              {selected.network && selected.network.influences.length > 0 ? (
                <ul className="factor-list">
                  {selected.network.influences.map((inf, i) => {
                    const lean = inf.signed > 0 ? 'bullish' : inf.signed < 0 ? 'bearish' : 'neutral';
                    return (<li key={i}><b>{inf.type} {inf.neighbour}</b> — news {inf.edge_sentiment} ({lean})</li>);
                  })}
                </ul>
              ) : (
                <p className="muted">No outgoing network edges.</p>
              )}
              <Link to={`/?ticker=${encodeURIComponent(selected.id)}`}>Open in Dashboard →</Link>
            </div>
          ) : (
            <div className="graph-legend">
              <p className="muted">Click a node for its detail, then Expand to grow the graph.</p>
              <p className="label">
                <span style={{ color: '#3fb950' }}>●</span> buy{' '}
                <span style={{ color: '#f85149' }}>●</span> sell{' '}
                <span style={{ color: '#8b949e' }}>●</span> hold · edge colour = news effect
              </p>
            </div>
          )}
        </div>
      ) : (
        <div className="graph-tab">
          {saved.length > 0 ? (
            <div className="graph-saves">
              {saved.map((s) => (
                <div key={s.root} className="graph-save-row">
                  <button className="linklike" onClick={() => onLoadSaved(s.root, undefined)}>Load {s.root}</button>
                  {s.versions.length > 1 && (
                    <select defaultValue="" onChange={(e) => { if (e.target.value) onLoadSaved(s.root, e.target.value); }}>
                      <option value="">latest ({s.versions.length})</option>
                      {s.versions.map((v) => <option key={v} value={v}>{new Date(v).toLocaleString()}</option>)}
                    </select>
                  )}
                  <button className="icon-btn" aria-label={`delete ${s.root}`} onClick={() => onDeleteSaved(s.root, undefined)}>✕</button>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">No saved graphs yet. Explore a company, then Save.</p>
          )}
        </div>
      )}
    </aside>
  );
}
