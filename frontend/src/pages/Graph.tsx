import { useMemo, useState } from 'react';
import { GraphCanvas } from '../components/GraphCanvas';
import { GraphSidebar } from '../components/GraphSidebar';
import { useGraph, useRebuildGraph, useScreen, useSectors } from '../hooks/queries';
import { applyFilters, mergeNodes, toLinks, type ViewNode } from '../lib/graphView';
import type { RelationType } from '../types';

const ALL_TYPES: RelationType[] = ['supplier', 'customer', 'partner', 'competitor', 'owner', 'subsidiary'];

export default function Graph() {
  const graph = useGraph();
  const board = useScreen(undefined, undefined, 0); // full uncapped board for node colour/size
  const sectors = useSectors();
  const rebuild = useRebuildGraph();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sector, setSector] = useState('');
  const [enabledTypes, setEnabledTypes] = useState<Set<RelationType>>(new Set(ALL_TYPES));

  const view = useMemo(() => {
    if (!graph.data) return { nodes: [] as ViewNode[], links: [] };
    return applyFilters(mergeNodes(graph.data, board.data), toLinks(graph.data), sector || null, enabledTypes);
  }, [graph.data, board.data, sector, enabledTypes]);

  const selected = useMemo(
    () => view.nodes.find((n) => n.id === selectedId) ?? null,
    [view.nodes, selectedId],
  );

  const toggleType = (t: RelationType) =>
    setEnabledTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });

  const g = graph.data;
  const empty = !!g && g.nodes.length === 0;

  return (
    <div className="graph-page">
      <div className="graph-main panel">
        {graph.isLoading && <p className="muted">Loading graph…</p>}
        {graph.isError && <p className="error">Could not load the graph: {(graph.error as Error).message}</p>}
        {empty && (
          <div className="graph-empty">
            <p className="muted">
              No graph yet — hit <b>Rebuild graph</b> to extract relationships (runs the LLM over your focus set).
            </p>
          </div>
        )}
        {!empty && g && (
          <GraphCanvas nodes={view.nodes} links={view.links} selectedId={selectedId} onSelect={setSelectedId} />
        )}
      </div>

      <GraphSidebar
        asOf={g?.as_of ?? ''}
        built={g?.built ?? 0}
        skipped={g?.skipped ?? 0}
        nodeCount={view.nodes.length}
        linkCount={view.links.length}
        sectors={sectors.data ?? []}
        sector={sector}
        onSector={setSector}
        enabledTypes={enabledTypes}
        onToggleType={toggleType}
        selected={selected}
        onRebuild={() => rebuild.mutate()}
        rebuilding={rebuild.isPending}
      />
    </div>
  );
}
