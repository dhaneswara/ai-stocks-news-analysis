import { useEffect, useMemo, useState } from 'react';
import { GraphCanvas } from '../components/GraphCanvas';
import { GraphSidebar } from '../components/GraphSidebar';
import {
  useDeleteSavedGraph, useEgoGraph, useFocusGraph, useLoadSavedGraph,
  useRebuildGraph, useSaveGraph, useSavedGraphs, useScreen,
} from '../hooks/queries';
import { applyFilters, mergeGraph, mergeNodes, toLinks, type ViewNode } from '../lib/graphView';
import { loadExplorerState, saveExplorerState } from '../lib/explorerStore';
import type { KnowledgeGraph, RelationType } from '../types';

const ALL_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary'];
const EMPTY_GRAPH: KnowledgeGraph = { as_of: '', scope: 'explore', nodes: [], edges: [], built: 0, skipped: 0 };

export default function Graph() {
  const restored = useMemo(() => loadExplorerState(), []);
  const board = useScreen(undefined, undefined, 0); // full uncapped board for node colour/size
  const ego = useEgoGraph();
  const focus = useFocusGraph();
  const rebuild = useRebuildGraph();
  const saved = useSavedGraphs();
  const saveGraph = useSaveGraph();
  const loadSaved = useLoadSavedGraph();
  const deleteSaved = useDeleteSavedGraph();

  const [working, setWorking] = useState<KnowledgeGraph | null>(restored?.working ?? null);
  const [root, setRoot] = useState(restored?.root ?? '');
  const [expanded, setExpanded] = useState<Set<string>>(new Set(restored?.expanded ?? []));
  const [selectedId, setSelectedId] = useState<string | null>(restored?.selectedId ?? null);
  const [enabledTypes, setEnabledTypes] = useState<Set<RelationType>>(new Set(ALL_TYPES));
  const [notice, setNotice] = useState<string | null>(null);

  // Persist the exploration so switching menus / reloading restores it.
  useEffect(() => {
    saveExplorerState({ working, root, expanded: [...expanded], selectedId });
  }, [working, root, expanded, selectedId]);

  const loadRoot = async (ticker: string) => {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setNotice(null);
    try {
      const frag = await ego.mutateAsync(t);
      setWorking(frag); setRoot(t); setExpanded(new Set()); setSelectedId(t);
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

  const loadFocus = async () => {
    setNotice(null);
    try {
      const g = await focus.mutateAsync();
      setWorking(g); setRoot(''); setExpanded(new Set()); setSelectedId(null);
      if (g.nodes.length === 0) setNotice('No focus graph yet — Rebuild focus to extract it.');
    } catch { /* surfaced via the load-error banner */ }
  };

  const doRebuild = async () => {
    setNotice(null);
    try {
      const g = await rebuild.mutateAsync();
      setWorking(g); setRoot(''); setExpanded(new Set()); setSelectedId(null);
    } catch { /* surfaced via the load-error banner */ }
  };

  const doSave = async () => {
    if (!working || working.nodes.length === 0) return;
    // No explicit root (e.g. after "Load focus set") -> key the save off the first node.
    try {
      await saveGraph.mutateAsync({
        root: root || working.nodes[0], saved_at: '', expanded: [...expanded], graph: working,
      });
    } catch { setNotice('Could not save this graph.'); }
  };

  const doLoadSaved = async (r: string, version?: string) => {
    setNotice(null);
    try {
      const v = await loadSaved.mutateAsync({ root: r, version });
      setWorking(v.graph); setRoot(v.root); setExpanded(new Set(v.expanded)); setSelectedId(v.root || null);
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

  const view = useMemo(() => {
    const g = working ?? EMPTY_GRAPH;
    return applyFilters(mergeNodes(g, board.data), toLinks(g), null, enabledTypes);
  }, [working, board.data, enabledTypes]);

  const selected = useMemo<ViewNode | null>(
    () => view.nodes.find((n) => n.id === selectedId) ?? null,
    [view.nodes, selectedId],
  );

  const busy = ego.isPending || focus.isPending;
  const loadErr = ego.isError
    ? (ego.error as Error).message
    : focus.isError
    ? (focus.error as Error).message
    : rebuild.isError
    ? (rebuild.error as Error).message
    : null;
  const empty = !working || working.nodes.length === 0;

  return (
    <div className="graph-page">
      <div className="graph-main panel">
        {busy && <p className="muted">Loading…</p>}
        {loadErr && <p className="error">Couldn't load: {loadErr}</p>}
        {notice && <p className="muted">{notice}</p>}
        {empty && !busy && (
          <div className="graph-empty">
            <p className="muted">Type a company ticker to start, or load the focus set.</p>
          </div>
        )}
        {!empty && (
          <GraphCanvas nodes={view.nodes} links={view.links} selectedId={selectedId} onSelect={setSelectedId} />
        )}
      </div>

      <GraphSidebar
        root={root}
        onLoadRoot={loadRoot}
        onExpand={expand}
        onLoadFocus={loadFocus}
        onRebuild={doRebuild}
        rebuilding={rebuild.isPending}
        loading={busy}
        canSave={!!working && working.nodes.length > 0}
        onSave={doSave}
        saving={saveGraph.isPending}
        saved={saved.data ?? []}
        onLoadSaved={doLoadSaved}
        onDeleteSaved={doDeleteSaved}
        nodeCount={view.nodes.length}
        linkCount={view.links.length}
        enabledTypes={enabledTypes}
        onToggleType={toggleType}
        selected={selected}
      />
    </div>
  );
}
