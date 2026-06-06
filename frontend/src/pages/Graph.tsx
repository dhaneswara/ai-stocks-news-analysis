import { useMemo, useState } from 'react';
import { GraphCanvas } from '../components/GraphCanvas';
import { GraphSidebar } from '../components/GraphSidebar';
import {
  useDeleteSavedGraph, useEgoGraph, useFocusGraph, useLoadSavedGraph,
  useRebuildGraph, useSaveGraph, useSavedGraphs, useScreen, useSectors,
} from '../hooks/queries';
import { applyFilters, mergeGraph, mergeNodes, toLinks, type ViewNode } from '../lib/graphView';
import type { KnowledgeGraph, RelationType } from '../types';

const ALL_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary'];
const EMPTY_GRAPH: KnowledgeGraph = { as_of: '', scope: 'explore', nodes: [], edges: [], built: 0, skipped: 0 };

export default function Graph() {
  const board = useScreen(undefined, undefined, 0); // full uncapped board for node colour/size
  const sectors = useSectors();
  const ego = useEgoGraph();
  const focus = useFocusGraph();
  const rebuild = useRebuildGraph();
  const saved = useSavedGraphs();
  const saveGraph = useSaveGraph();
  const loadSaved = useLoadSavedGraph();
  const deleteSaved = useDeleteSavedGraph();

  const [working, setWorking] = useState<KnowledgeGraph | null>(null);
  const [root, setRoot] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sector, setSector] = useState('');
  const [enabledTypes, setEnabledTypes] = useState<Set<RelationType>>(new Set(ALL_TYPES));
  const [notice, setNotice] = useState<string | null>(null);

  const loadRoot = async (ticker: string) => {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setNotice(null);
    const frag = await ego.mutateAsync(t);
    setWorking(frag); setRoot(t); setExpanded(new Set()); setSelectedId(t);
    if (frag.edges.length === 0) setNotice(`No relationships found for ${t}.`);
  };

  const expand = async (ticker: string) => {
    setNotice(null);
    const frag = await ego.mutateAsync(ticker);
    setWorking((w) => mergeGraph(w, frag));
    setExpanded((s) => new Set(s).add(ticker));
    if (frag.edges.length === 0) setNotice(`No further relationships for ${ticker}.`);
  };

  const loadFocus = async () => {
    setNotice(null);
    const g = await focus.mutateAsync();
    setWorking(g); setRoot(''); setExpanded(new Set()); setSelectedId(null);
    if (g.nodes.length === 0) setNotice('No focus graph yet — Rebuild focus to extract it.');
  };

  const doRebuild = async () => {
    setNotice(null);
    const g = await rebuild.mutateAsync();
    setWorking(g); setRoot(''); setExpanded(new Set()); setSelectedId(null);
  };

  const doSave = async () => {
    if (!working || working.nodes.length === 0) return;
    await saveGraph.mutateAsync({
      root: root || working.nodes[0], saved_at: '', expanded: [...expanded], graph: working,
    });
  };

  const doLoadSaved = async (r: string, version?: string) => {
    const v = await loadSaved.mutateAsync({ root: r, version });
    setWorking(v.graph); setRoot(v.root); setExpanded(new Set(v.expanded)); setSelectedId(v.root || null);
  };

  const doDeleteSaved = async (r: string, version?: string) => {
    await deleteSaved.mutateAsync({ root: r, version });
  };

  const toggleType = (t: RelationType) =>
    setEnabledTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  const resetFilters = () => { setSector(''); setEnabledTypes(new Set(ALL_TYPES)); };

  const view = useMemo(() => {
    const g = working ?? EMPTY_GRAPH;
    return applyFilters(mergeNodes(g, board.data), toLinks(g), sector || null, enabledTypes);
  }, [working, board.data, sector, enabledTypes]);

  const selected = useMemo<ViewNode | null>(
    () => view.nodes.find((n) => n.id === selectedId) ?? null,
    [view.nodes, selectedId],
  );

  const busy = ego.isPending || focus.isPending;
  const empty = !working || working.nodes.length === 0;
  const filteredEmpty = !empty && view.nodes.length === 0;

  return (
    <div className="graph-page">
      <div className="graph-main panel">
        {busy && <p className="muted">Loading…</p>}
        {ego.isError && <p className="error">Couldn't load: {(ego.error as Error).message}</p>}
        {notice && <p className="muted">{notice}</p>}
        {empty && !busy && (
          <div className="graph-empty">
            <p className="muted">Type a company ticker to start, or load the focus set.</p>
          </div>
        )}
        {filteredEmpty && (
          <div className="graph-empty">
            <p className="muted">No nodes match these filters.</p>
            <button className="secondary" onClick={resetFilters}>Reset filters</button>
          </div>
        )}
        {!empty && !filteredEmpty && (
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
        sectors={sectors.data ?? []}
        sector={sector}
        onSector={setSector}
        enabledTypes={enabledTypes}
        onToggleType={toggleType}
        selected={selected}
      />
    </div>
  );
}
