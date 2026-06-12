import { useEffect, useMemo, useRef, useState } from 'react';
import { GraphCanvas } from '../components/GraphCanvas';
import { GraphSidebar } from '../components/GraphSidebar';
import { MergePreview } from '../components/MergePreview';
import {
  useActiveOntology, useDeleteImport, useDeleteOntology, useEgoGraph, useImportGraph, useImports,
  useLoadOntology, useOntologies, useSaveOntology, useScreen, useSetActiveOntology, useWatchlist,
} from '../hooks/queries';
import { addCompanyNode, addManualEdge, addManualNode, applyFilters, COMPANY_TICKER_RE, deleteEdge, deleteNode, mergeGraph, mergeNodes, resolveManualTarget, toLinks, type ViewNode } from '../lib/graphView';
import { loadExplorerState, saveExplorerState } from '../lib/explorerStore';
import type { EdgeSentiment, GraphEdge, ImportReport, KnowledgeGraph, RelationType } from '../types';
import { api } from '../api/client';

const ALL_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary', 'other'];
const EMPTY_GRAPH: KnowledgeGraph = { as_of: '', scope: 'explore', nodes: [], edges: [], built: 0, skipped: 0 };

export default function Graph() {
  const restored = useMemo(() => loadExplorerState(), []);
  const board = useScreen(undefined, undefined, 0); // full uncapped board for node colour/size
  const ego = useEgoGraph();
  const ontologies = useOntologies();
  const activeOnto = useActiveOntology();
  const saveOntology = useSaveOntology();
  const loadOntology = useLoadOntology();
  const deleteOntology = useDeleteOntology();
  const setActiveOnto = useSetActiveOntology();

  const watch = useWatchlist();
  const toggleWatch = (id: string) => (watch.list.includes(id) ? watch.remove(id) : watch.add(id));

  const imports = useImports();
  const importGraph = useImportGraph();
  const deleteImport = useDeleteImport();
  const [importReport, setImportReport] = useState<ImportReport | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const doImport = async (name: string, payload: unknown) => {
    setImportError(null);
    setImportReport(null);
    try {
      const report = await importGraph.mutateAsync({ name, payload });
      setImportReport(report);
    } catch {
      setImportError('Could not import this model.');
    }
  };

  const doDeleteImport = async (id: string) => {
    try {
      await deleteImport.mutateAsync(id);
      setImportReport(null);
    } catch { setImportError('Could not remove the set.'); }
  };

  const [tab, setTab] = useState<'explore' | 'saved' | 'import'>('explore');
  const [working, setWorking] = useState<KnowledgeGraph | null>(restored?.working ?? null);
  const [root, setRoot] = useState(restored?.root ?? '');
  const [expanded, setExpanded] = useState<Set<string>>(new Set(restored?.expanded ?? []));
  const [selectedId, setSelectedId] = useState<string | null>(restored?.selectedId ?? null);
  const [enabledTypes, setEnabledTypes] = useState<Set<RelationType>>(new Set(ALL_TYPES));
  const [notice, setNotice] = useState<string | null>(null);
  const [ontologyName, setOntologyName] = useState(restored?.ontologyName ?? '');

  const [addingFrom, setAddingFrom] = useState<string | null>(null);
  const [addingCompany, setAddingCompany] = useState(false);
  const [mergeSetId, setMergeSetId] = useState<string | null>(null);
  const [mergeImport, setMergeImport] = useState<KnowledgeGraph | null>(null);
  const [dirty, setDirty] = useState(false);

  // Persist the exploration so switching menus / reloading restores it.
  useEffect(() => {
    saveExplorerState({ working, root, expanded: [...expanded], selectedId, ontologyName });
  }, [working, root, expanded, selectedId, ontologyName]);

  const selectNode = (id: string) => { setSelectedId(id); setTab('explore'); };

  const loadRoot = async (ticker: string) => {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setNotice(null);
    try {
      const frag = await ego.mutateAsync(t);
      setWorking(frag); setRoot(t); setExpanded(new Set()); setSelectedId(t); setTab('explore');
      setOntologyName(''); setDirty(false);
      if (frag.edges.length === 0) setNotice(`No relationships found for ${t}.`);
    } catch { /* surfaced via the load-error banner */ }
  };

  const expand = async (ticker: string) => {
    setNotice(null);
    try {
      const frag = await ego.mutateAsync(ticker);
      setWorking((w) => mergeGraph(w, frag));
      setExpanded((s) => new Set(s).add(ticker));
      setDirty(true);
      if (frag.edges.length === 0) setNotice(`No further relationships for ${ticker}.`);
    } catch { /* surfaced via the load-error banner */ }
  };

  const doSaveAs = async (name: string) => {
    const n = name.trim();
    if (!working || working.nodes.length === 0) return;
    if (!n) { setNotice('Name the ontology first.'); return; }
    setNotice(null);
    try {
      const saved = await saveOntology.mutateAsync({
        name: n, saved_at: '', expanded: [...expanded], graph: working,
      });
      setOntologyName(saved.name);   // canonical spelling from the server
      setDirty(false);
    } catch { setNotice('Could not save this ontology.'); }
  };

  const doNew = () => {
    setWorking(null); setOntologyName(''); setRoot(''); setExpanded(new Set());
    setSelectedId(null); setNotice(null); setDirty(false); setAddingCompany(false);
  };

  const doLoadOntology = async (name: string, version?: string) => {
    setNotice(null);
    try {
      const v = await loadOntology.mutateAsync({ name, version });
      setWorking(v.graph); setOntologyName(v.name); setExpanded(new Set(v.expanded));
      setRoot(''); setSelectedId(null); setTab('explore');
      // A historical revision is NOT the live one: dirty until re-saved (Save = restore).
      const latest = ontologies.data?.find((o) => o.name === v.name)?.versions[0];
      setDirty(!!version && version !== latest);
    } catch { setNotice(`Could not load the ontology ${name}.`); }
  };

  const doDeleteOntology = async (name: string, version?: string) => {
    try { await deleteOntology.mutateAsync({ name, version }); }
    catch { setNotice(`Could not delete ${name}.`); }
  };

  const doActivate = async (name: string | null) => {
    setNotice(null);
    try { await setActiveOnto.mutateAsync(name); }
    catch { setNotice('Could not change the active ontology.'); }
  };

  // Boot precedence: restored canvas wins; otherwise load the active ontology once; otherwise empty canvas.
  const booted = useRef(false);
  useEffect(() => {
    if (booted.current || restored?.working || working || !activeOnto.data?.name) return;
    booted.current = true;
    void doLoadOntology(activeOnto.data.name);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- boot-once on first active fetch
  }, [activeOnto.data]);

  const toggleType = (t: RelationType) =>
    setEnabledTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });

  const startMerge = async (id: string) => {
    setNotice(null);
    try {
      const set = await api.getImportSet(id);
      setMergeSetId(id); setMergeImport(set); setTab('import');
    } catch { setNotice('Could not load that import set.'); }
  };

  const applyMergeResult = (merged: KnowledgeGraph) => {
    setWorking(merged); setMergeImport(null); setMergeSetId(null); setDirty(true);
  };

  const cancelMerge = () => { setMergeImport(null); setMergeSetId(null); };

  const addCompany = (data: { ticker: string; label: string }) => {
    const t = data.ticker.trim();
    if (!COMPANY_TICKER_RE.test(t)) { setNotice('Ticker must be 1–10 letters/digits, e.g. TSM.'); return; }
    const base = working ?? { ...EMPTY_GRAPH, nodes: [], edges: [], node_meta: {} };
    setWorking(addCompanyNode(base, { ticker: t, label: data.label }));
    setSelectedId(t.toUpperCase()); setDirty(true); setAddingCompany(false); setNotice(null);
  };

  const addRelationship = (data: { target: string; type: RelationType; sentiment: EdgeSentiment; note: string }) => {
    if (!working || !addingFrom) return;
    const t = resolveManualTarget(data.target, working, board.data?.items ?? []);
    const edge: GraphEdge = {
      source: addingFrom, target: t.id, type: data.type, sentiment: data.sentiment,
      weight: 0.5, confidence: 0.9, evidence: data.note, url: '', as_of: new Date().toISOString(), origin: 'manual',
    };
    // Create a brand-new concept/external target with its human label first (so it isn't labelled
    // by its id); addManualEdge then attaches the edge (no-op node-create for ids that exist).
    const base = t.external && t.isNew ? addManualNode(working, { id: t.id, label: t.label }) : working;
    setWorking(addManualEdge(base, edge)); setDirty(true); setAddingFrom(null);
  };

  const removeNode = (id: string) => {
    if (!working) return;
    const hasEdges = working.edges.some((e) => e.source === id || e.target === id);
    if (hasEdges && !window.confirm(`Delete ${id} and its relationships?`)) return;
    setWorking(deleteNode(working, id));
    if (selectedId === id) setSelectedId(null);
    setDirty(true);
  };

  const removeEdge = (ref: { source: string; target: string; type: RelationType }) => {
    if (!working) return;
    setWorking(deleteEdge(working, ref)); setDirty(true);
  };

  const view = useMemo(() => {
    const g = working ?? EMPTY_GRAPH;
    return applyFilters(mergeNodes(g, board.data), toLinks(g), null, enabledTypes);
  }, [working, board.data, enabledTypes]);

  const selected = useMemo<ViewNode | null>(
    () => view.nodes.find((n) => n.id === selectedId) ?? null,
    [view.nodes, selectedId],
  );

  const busy = ego.isPending;
  const loadErr = ego.isError ? (ego.error as Error).message : null;
  const empty = !working || working.nodes.length === 0;

  const activeName = activeOnto.data?.name ?? null;
  const onActive = !dirty && !!ontologyName && ontologyName === activeName;
  const hint = onActive ? null
    : `Analysis currently uses ${activeName ? `"${activeName}"` : 'no network signal'}${dirty ? ' — unsaved changes here' : ''}.`;

  return (
    <div className="graph-page">
      <div className="graph-main panel">
        {busy && <p className="muted">Loading…</p>}
        {loadErr && <p className="error">Couldn't load: {loadErr}</p>}
        {notice && <p className="muted">{notice}</p>}
        <div className="ontology-bar">
          <input
            placeholder="Ontology name" aria-label="ontology name"
            value={ontologyName} onChange={(e) => setOntologyName(e.target.value)}
          />
          <button
            disabled={!working || working.nodes.length === 0 || saveOntology.isPending}
            onClick={() => { void doSaveAs(ontologyName); }}
          >
            {saveOntology.isPending ? 'Saving…' : 'Save'}
          </button>
          <button
            className="secondary" disabled={!working || working.nodes.length === 0}
            onClick={() => { const n = window.prompt('Save as…', ontologyName ? `${ontologyName} copy` : ''); if (n) void doSaveAs(n); }}
          >
            Save as
          </button>
          <button className="secondary" onClick={doNew}>New</button>
          {hint && <span className="muted">{hint}</span>}
        </div>
        {empty && !busy && (
          <div className="graph-empty">
            <p className="muted">Type a company ticker in the panel to start exploring.</p>
          </div>
        )}
        {!empty && (
          <GraphCanvas
            nodes={view.nodes} links={view.links} selectedId={selectedId} onSelect={selectNode}
            onAddRelationship={(id) => { setAddingFrom(id); setAddingCompany(false); setTab('explore'); }}
            onAddCompany={() => { setAddingCompany(true); setAddingFrom(null); setTab('explore'); }}
            onDeleteNode={removeNode}
            onDeleteEdge={removeEdge}
            watchlist={watch.list}
            onToggleWatch={toggleWatch}
          />
        )}
        {mergeImport && (
          <MergePreview
            key={mergeSetId ?? 'merge'}
            working={working ?? EMPTY_GRAPH} importSet={mergeImport} board={board.data?.items ?? []}
            onApply={applyMergeResult} onCancel={cancelMerge}
          />
        )}
      </div>

      <GraphSidebar
        tab={tab}
        onTab={setTab}
        onLoadRoot={loadRoot}
        onExpand={expand}
        loading={busy}
        nodeCount={view.nodes.length}
        linkCount={view.links.length}
        enabledTypes={enabledTypes}
        onToggleType={toggleType}
        selected={selected}
        imports={imports.data ?? []}
        onImport={doImport}
        onDeleteImport={doDeleteImport}
        importing={importGraph.isPending}
        importReport={importReport}
        importError={importError}
        addingFrom={addingFrom}
        onSubmitRelationship={addRelationship}
        onCancelRelationship={() => setAddingFrom(null)}
        addingCompany={addingCompany}
        onSubmitCompany={addCompany}
        onCancelCompany={() => setAddingCompany(false)}
        onStartAddCompany={() => { setAddingCompany(true); setAddingFrom(null); setTab('explore'); }}
        onMergeImport={startMerge}
        promptDefault={selectedId || root || ''}
        ontologies={ontologies.data ?? []}
        activeName={activeName}
        onLoadOntology={doLoadOntology}
        onDeleteOntology={doDeleteOntology}
        onActivate={doActivate}
        watchlist={watch.list}
        onToggleWatch={toggleWatch}
      />
    </div>
  );
}
