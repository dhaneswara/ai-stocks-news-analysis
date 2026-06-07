import { useEffect, useMemo, useState } from 'react';
import { GraphCanvas } from '../components/GraphCanvas';
import { GraphSidebar } from '../components/GraphSidebar';
import { MergePreview } from '../components/MergePreview';
import {
  useDeleteImport, useDeleteSavedGraph, useEgoGraph, useImportGraph, useImports,
  useLoadSavedGraph, useOverlay, useSaveGraph, useSavedGraphs, useScreen,
} from '../hooks/queries';
import { addManualEdge, addManualNode, applyFilters, deleteEdge, deleteNode, mergeGraph, mergeNodes, resolveManualTarget, toLinks, type ViewNode } from '../lib/graphView';
import { loadExplorerState, saveExplorerState } from '../lib/explorerStore';
import type { EdgeSentiment, GraphEdge, ImportReport, KnowledgeGraph, RelationType } from '../types';
import { api } from '../api/client';

const ALL_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary', 'other'];
const EMPTY_GRAPH: KnowledgeGraph = { as_of: '', scope: 'explore', nodes: [], edges: [], built: 0, skipped: 0 };

export default function Graph() {
  const restored = useMemo(() => loadExplorerState(), []);
  const board = useScreen(undefined, undefined, 0); // full uncapped board for node colour/size
  const ego = useEgoGraph();
  const saved = useSavedGraphs();
  const saveGraph = useSaveGraph();
  const loadSaved = useLoadSavedGraph();
  const deleteSaved = useDeleteSavedGraph();

  const imports = useImports();
  const overlay = useOverlay();
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

  const [addingFrom, setAddingFrom] = useState<string | null>(null);
  const [mergeSetId, setMergeSetId] = useState<string | null>(null);
  const [mergeImport, setMergeImport] = useState<KnowledgeGraph | null>(null);
  const [dirty, setDirty] = useState(false);

  // Persist the exploration so switching menus / reloading restores it.
  useEffect(() => {
    saveExplorerState({ working, root, expanded: [...expanded], selectedId });
  }, [working, root, expanded, selectedId]);

  const selectNode = (id: string) => { setSelectedId(id); setTab('explore'); };

  const loadRoot = async (ticker: string) => {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setNotice(null);
    try {
      const frag = await ego.mutateAsync(t);
      setWorking(frag); setRoot(t); setExpanded(new Set()); setSelectedId(t); setTab('explore');
      setDirty(false);
      if (frag.edges.length === 0) setNotice(`No relationships found for ${t}.`);
    } catch { /* surfaced via the load-error banner */ }
  };

  const expand = async (ticker: string) => {
    setNotice(null);
    try {
      const frag = await ego.mutateAsync(ticker);
      setWorking((w) => mergeGraph(w, frag));
      setExpanded((s) => new Set(s).add(ticker));
      if (frag.edges.length === 0) setNotice(`No further relationships for ${ticker}.`);
    } catch { /* surfaced via the load-error banner */ }
  };

  const clearGraph = () => {
    setWorking(null); setRoot(''); setExpanded(new Set()); setSelectedId(null); setNotice(null);
    setDirty(false);
  };

  const doSave = async () => {
    if (!working || working.nodes.length === 0) return;
    // No explicit root (e.g. a loaded graph) -> key the save off the first node.
    try {
      await saveGraph.mutateAsync({
        root: root || working.nodes[0], saved_at: '', expanded: [...expanded], graph: working,
      });
      setDirty(false);
    } catch { setNotice('Could not save this graph.'); }
  };

  const doLoadSaved = async (r: string, version?: string) => {
    setNotice(null);
    try {
      const v = await loadSaved.mutateAsync({ root: r, version });
      setWorking(v.graph); setRoot(v.root); setExpanded(new Set(v.expanded)); setSelectedId(v.root || null);
      setTab('explore');
      setDirty(false);
    } catch { setNotice(`Could not load the saved graph for ${r}.`); }
  };

  const doDeleteSaved = async (r: string, version?: string) => {
    try {
      await deleteSaved.mutateAsync({ root: r, version });
    } catch { setNotice(`Could not delete the saved graph for ${r}.`); }
  };

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
    let merged = g;
    const ov = overlay.data;
    if (ov && ov.edges.length) {
      const present = new Set(g.nodes);
      const incident = ov.edges.filter((e) => present.has(e.source) || present.has(e.target));
      if (incident.length) {
        const incidentIds = new Set(incident.flatMap((e) => [e.source, e.target]));
        const frag: KnowledgeGraph = {
          ...ov,
          edges: incident,
          nodes: Array.from(incidentIds),
          node_meta: Object.fromEntries(
            Object.entries(ov.node_meta ?? {}).filter(([id]) => incidentIds.has(id)),
          ),
        };
        merged = mergeGraph(g, frag);
      }
    }
    return applyFilters(mergeNodes(merged, board.data), toLinks(merged), null, enabledTypes);
  }, [working, board.data, enabledTypes, overlay.data]);

  const selected = useMemo<ViewNode | null>(
    () => view.nodes.find((n) => n.id === selectedId) ?? null,
    [view.nodes, selectedId],
  );

  const busy = ego.isPending;
  const loadErr = ego.isError ? (ego.error as Error).message : null;
  const empty = !working || working.nodes.length === 0;

  return (
    <div className="graph-page">
      <div className="graph-main panel">
        {busy && <p className="muted">Loading…</p>}
        {loadErr && <p className="error">Couldn't load: {loadErr}</p>}
        {notice && <p className="muted">{notice}</p>}
        {dirty && <p className="muted unsaved-hint">Unsaved changes — click Save to keep them.</p>}
        {empty && !busy && (
          <div className="graph-empty">
            <p className="muted">Type a company ticker in the panel to start exploring.</p>
          </div>
        )}
        {!empty && (
          <GraphCanvas
            nodes={view.nodes} links={view.links} selectedId={selectedId} onSelect={selectNode}
            onAddRelationship={(id) => { setAddingFrom(id); setTab('explore'); }}
            onDeleteNode={removeNode}
            onDeleteEdge={removeEdge}
          />
        )}
        {mergeImport && working && (
          <MergePreview
            key={mergeSetId ?? 'merge'}
            working={working} importSet={mergeImport} board={board.data?.items ?? []}
            onApply={applyMergeResult} onCancel={cancelMerge}
          />
        )}
      </div>

      <GraphSidebar
        tab={tab}
        onTab={setTab}
        onLoadRoot={loadRoot}
        onExpand={expand}
        onSave={doSave}
        onClear={clearGraph}
        canSave={!!working && working.nodes.length > 0}
        saving={saveGraph.isPending}
        loading={busy}
        saved={saved.data ?? []}
        onLoadSaved={doLoadSaved}
        onDeleteSaved={doDeleteSaved}
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
        onMergeImport={startMerge}
        promptDefault={selectedId || root || ''}
      />
    </div>
  );
}
