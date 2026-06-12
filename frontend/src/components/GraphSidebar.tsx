import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { EdgeSentiment, ImportReport, ImportSetSummary, OntologySummary, RelationType } from '../types';
import type { ViewNode } from '../lib/graphView';
import { chatGptPrompt } from '../lib/importPrompt';

const EDGE_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary', 'other'];

export interface GraphSidebarProps {
  tab: 'explore' | 'saved' | 'import';
  onTab: (t: 'explore' | 'saved' | 'import') => void;
  onLoadRoot: (ticker: string) => void;
  onExpand: (ticker: string) => void;
  loading: boolean;
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
  addingFrom: string | null;
  onSubmitRelationship: (data: { target: string; type: RelationType; sentiment: EdgeSentiment; note: string }) => void;
  onCancelRelationship: () => void;
  addingCompany: boolean;
  onSubmitCompany: (d: { ticker: string; label: string }) => void;
  onCancelCompany: () => void;
  onStartAddCompany: () => void;
  onMergeImport: (id: string) => void;
  promptDefault: string;
  ontologies: OntologySummary[];
  activeName: string | null;
  onLoadOntology: (name: string, version?: string) => void;
  onDeleteOntology: (name: string, version?: string) => void;
  onActivate: (name: string | null) => void;
}

export function GraphSidebar(props: GraphSidebarProps) {
  const {
    tab, onTab, onLoadRoot, onExpand, loading,
    nodeCount, linkCount, enabledTypes, onToggleType, selected,
    imports, onImport, onDeleteImport, importing, importReport, importError,
    addingFrom, onSubmitRelationship, onCancelRelationship,
    addingCompany, onSubmitCompany, onCancelCompany, onStartAddCompany,
    onMergeImport,
    promptDefault,
    ontologies, activeName, onLoadOntology, onDeleteOntology, onActivate,
  } = props;
  const [rootInput, setRootInput] = useState('');
  const [jsonText, setJsonText] = useState('');
  const [setName, setSetName] = useState('');
  const [parseError, setParseError] = useState<string | null>(null);
  const [relTarget, setRelTarget] = useState('');
  const [relType, setRelType] = useState<RelationType>('supplier');
  const [relEffect, setRelEffect] = useState<EdgeSentiment>('positive');
  const [relNote, setRelNote] = useState('');
  const [coTicker, setCoTicker] = useState('');
  const [coLabel, setCoLabel] = useState('');

  const submitCompany = () => {
    if (!coTicker.trim()) return;
    onSubmitCompany({ ticker: coTicker.trim(), label: coLabel.trim() });
    setCoTicker(''); setCoLabel('');
  };

  const submitRel = () => {
    if (!relTarget.trim()) return;
    onSubmitRelationship({ target: relTarget.trim(), type: relType, sentiment: relEffect, note: relNote.trim() });
    setRelTarget(''); setRelType('supplier'); setRelEffect('positive'); setRelNote('');
  };

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
          Ontologies{ontologies.length ? ` (${ontologies.length})` : ''}
        </button>
        <button type="button" className={`tab${tab === 'import' ? ' active' : ''}`} onClick={() => onTab('import')}>
          Import
        </button>
      </div>

      {tab === 'explore' && (
        <div className="graph-tab">
          {addingCompany && (
            <div className="graph-section rel-form">
              <span className="label">Add a company</span>
              <input placeholder="Ticker (e.g. TSM)" value={coTicker} onChange={(e) => setCoTicker(e.target.value)}
                     onKeyDown={(e) => { if (e.key === 'Enter') submitCompany(); }} />
              <input placeholder="Name (optional)" value={coLabel} onChange={(e) => setCoLabel(e.target.value)} />
              <div className="graph-actions">
                <button onClick={submitCompany}>Add</button>
                <button className="secondary" onClick={onCancelCompany}>Cancel</button>
              </div>
            </div>
          )}
          {addingFrom && (
            <div className="graph-section rel-form">
              <span className="label">Add relationship from <b>{addingFrom}</b></span>
              <input
                placeholder="Target (ticker or company)"
                value={relTarget}
                onChange={(e) => setRelTarget(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') submitRel(); }}
              />
              <select value={relType} onChange={(e) => setRelType(e.target.value as RelationType)} aria-label="relationship type">
                {EDGE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <select value={relEffect} onChange={(e) => setRelEffect(e.target.value as EdgeSentiment)} aria-label="effect on source">
                <option value="positive">helps</option>
                <option value="negative">hurts</option>
                <option value="neutral">neutral</option>
              </select>
              <input placeholder="Note (optional)" value={relNote} onChange={(e) => setRelNote(e.target.value)} />
              <div className="graph-actions">
                <button onClick={submitRel}>Add</button>
                <button className="secondary" onClick={onCancelRelationship}>Cancel</button>
              </div>
            </div>
          )}
          <label>Start from a company
            <input
              placeholder="Ticker (e.g. AAPL)"
              value={rootInput}
              onChange={(e) => setRootInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && rootInput.trim()) onLoadRoot(rootInput.trim()); }}
            />
          </label>
          <button disabled={loading || !rootInput.trim()} onClick={() => onLoadRoot(rootInput.trim())}>Start</button>
          <button className="secondary" onClick={onStartAddCompany}>Add company…</button>

          <div className="graph-section">
            <p className="muted">{nodeCount} nodes · {linkCount} edges</p>
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
              <p className="muted">Click a node for its detail, then Expand to grow the graph. Right-click a node or edge to add or delete.</p>
            </div>
          )}
        </div>
      )}

      {tab === 'saved' && (
        <div className="graph-tab">
          <div className="graph-save-row">
            <span className="muted">None (network signal off)</span>
            {activeName === null
              ? <span className="badge hold">ACTIVE</span>
              : <button className="linklike" onClick={() => onActivate(null)}>Set active</button>}
          </div>
          {ontologies.map((o) => (
            <div key={o.name} className="graph-save-row">
              <button className="linklike" onClick={() => onLoadOntology(o.name)}>Load {o.name}</button>
              <span className="muted">{o.node_count}n · {o.edge_count}e</span>
              {o.active
                ? <span className="badge buy">ACTIVE</span>
                : <button className="linklike" onClick={() => onActivate(o.name)}>Set active</button>}
              {o.versions.length > 1 && (
                <select defaultValue="" onChange={(e) => { if (e.target.value) onLoadOntology(o.name, e.target.value); }}>
                  <option value="">latest ({o.versions.length})</option>
                  {o.versions.map((v) => <option key={v} value={v}>{new Date(v).toLocaleString()}</option>)}
                </select>
              )}
              <button className="icon-btn" aria-label={`delete ${o.name}`} onClick={() => onDeleteOntology(o.name)}>✕</button>
            </div>
          ))}
          {ontologies.length === 0 && <p className="muted">No ontologies yet — build a graph and Save it.</p>}
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
                    <button className="linklike" aria-label={`merge ${s.name || s.id}`} onClick={() => onMergeImport(s.id)}>Merge into graph</button>
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
