import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { ImportReport, ImportSetSummary, RelationType, SavedGraphSummary } from '../types';
import type { ViewNode } from '../lib/graphView';
import { chatGptPrompt } from '../lib/importPrompt';

const EDGE_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary', 'other'];

export interface GraphSidebarProps {
  tab: 'explore' | 'saved' | 'import';
  onTab: (t: 'explore' | 'saved' | 'import') => void;
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
  imports: ImportSetSummary[];
  onImport: (name: string, payload: unknown) => void;
  onDeleteImport: (id: string) => void;
  importing: boolean;
  importReport: ImportReport | null;
  importError: string | null;
  promptDefault: string;
}

export function GraphSidebar(props: GraphSidebarProps) {
  const {
    tab, onTab, onLoadRoot, onExpand, onSave, onClear, canSave, saving, loading,
    saved, onLoadSaved, onDeleteSaved, nodeCount, linkCount, enabledTypes, onToggleType, selected,
    imports, onImport, onDeleteImport, importing, importReport, importError, promptDefault,
  } = props;
  const [rootInput, setRootInput] = useState('');
  const [jsonText, setJsonText] = useState('');
  const [setName, setSetName] = useState('');
  const [parseError, setParseError] = useState<string | null>(null);

  const doImport = () => {
    setParseError(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(jsonText);
    } catch {
      setParseError('Invalid JSON — check the pasted model.');
      return;
    }
    onImport(setName.trim(), parsed);
  };

  const onFile = (file: File | undefined) => {
    if (!file) return;
    setParseError(null);
    file.text().then((t) => setJsonText(t)).catch(() => setParseError('Could not read the file.'));
  };

  const copyPrompt = () => {
    navigator.clipboard?.writeText(chatGptPrompt(promptDefault)).catch(() => {});
  };

  return (
    <aside className="graph-sidebar panel">
      <div className="graph-tabs">
        <button type="button" className={`tab${tab === 'explore' ? ' active' : ''}`} onClick={() => onTab('explore')}>
          Explore
        </button>
        <button type="button" className={`tab${tab === 'saved' ? ' active' : ''}`} onClick={() => onTab('saved')}>
          Saved{saved.length ? ` (${saved.length})` : ''}
        </button>
        <button type="button" className={`tab${tab === 'import' ? ' active' : ''}`} onClick={() => onTab('import')}>
          Import
        </button>
      </div>

      {tab === 'explore' && (
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
      )}

      {tab === 'saved' && (
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

      {tab === 'import' && (
        <div className="graph-tab">
          <button type="button" className="secondary" onClick={copyPrompt}>Copy ChatGPT prompt</button>
          <p className="muted">Paste the model JSON your external tool produced:</p>
          <input placeholder="Set name (optional)" value={setName} onChange={(e) => setSetName(e.target.value)} />
          <textarea
            className="graph-json"
            placeholder="Paste import JSON…"
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            rows={8}
          />
          <input type="file" accept="application/json,.json" aria-label="Upload JSON file" onChange={(e) => onFile(e.target.files?.[0])} />
          <button disabled={importing || !jsonText.trim()} onClick={doImport}>
            {importing ? 'Importing…' : 'Import model'}
          </button>
          {parseError && <p className="error">{parseError}</p>}
          {importError && <p className="error">{importError}</p>}
          {importReport && (
            <p className="muted">
              Imported {importReport.edges_added} edges, {importReport.nodes_added} nodes
              {importReport.dropped ? `, ${importReport.dropped} dropped` : ''}.
              {importReport.warnings.map((w, i) => <span key={`${i}-${w}`}><br />{w}</span>)}
            </p>
          )}
          <div className="graph-section">
            <span className="label">Imported sets</span>
            {imports.length ? (
              <div className="graph-saves">
                {imports.map((s) => (
                  <div key={s.id} className="graph-save-row">
                    <span>{s.name || '(unnamed)'} · {s.edge_count} edges</span>
                    <button className="icon-btn" aria-label={`delete ${s.name || s.id}`} onClick={() => onDeleteImport(s.id)}>✕</button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">No imported models yet.</p>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
