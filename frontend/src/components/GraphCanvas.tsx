import { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from 'react-force-graph-2d';
import { directionColor, nodeRadius, sentimentColor, type ViewLink, type ViewNode } from '../lib/graphView';
import { GraphLegend } from './GraphLegend';
import { GraphContextMenu, type MenuItem } from './GraphContextMenu';
import type { RelationType } from '../types';

// The shapes react-force-graph hands our accessors: our view types plus the force sim's
// mutable coords (x/y/vx/vy) and object-ified link endpoints. NodeObject/LinkObject are
// idempotent under re-wrapping, so these line up with the component's inferred prop types.
type FGNode = NodeObject<ViewNode>;
type FGLink = LinkObject<ViewNode, ViewLink>;
type FGMethods = ForceGraphMethods<FGNode, FGLink>;

export interface GraphCanvasProps {
  nodes: ViewNode[];
  links: ViewLink[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Clicking empty canvas space clears the current selection. */
  onBackgroundClick: () => void;
  onAddRelationship: (sourceId: string) => void;
  onAddCompany: () => void;
  onRenameNode: (id: string) => void;
  onDeleteNode: (id: string) => void;
  onDeleteEdge: (ref: { source: string; target: string; type: RelationType }) => void;
  watchlist: string[];
  onToggleWatch: (id: string) => void;
  /** Camera command from the toolbar find box: bump `n` to centre on node `id`. */
  focus: { id: string; n: number } | null;
}

interface Menu { x: number; y: number; items: MenuItem[] }

export function GraphCanvas({
  nodes, links, selectedId, onSelect, onBackgroundClick, onAddRelationship, onAddCompany, onRenameNode, onDeleteNode, onDeleteEdge,
  watchlist, onToggleWatch, focus,
}: GraphCanvasProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const fgRef = useRef<FGMethods>();
  const fitNext = useRef(true);   // zoom-to-fit once after the next time the layout settles
  const [dims, setDims] = useState({ width: 600, height: 480 });
  const [menu, setMenu] = useState<Menu | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) =>
      setDims({ width: entry.contentRect.width, height: entry.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // The graph's shape: node ids + edge endpoints/type. A background board refetch hands us
  // fresh nodes/links arrays with identical shape (only scores differ) — rebuilding `data` on
  // those churns the force layout and re-fits the view, throwing away the user's zoom/pan.
  const topoSig = useMemo(
    // JSON of [node ids, [source,target,type] per edge] — unambiguous (quotes/brackets delimit),
    // so distinct shapes can't collide into one signature and a real change is never missed.
    () => JSON.stringify([nodes.map((n) => n.id), links.map((l) => [l.source, l.target, l.type])]),
    [nodes, links],
  );

  // Rebuild (and therefore re-layout + fit) only when the shape actually changes — expand,
  // add/remove a node or edge, a type-filter toggle, or loading a different ontology. Score-only
  // updates keep the same `data` reference, so the live zoom survives a board refetch.
  const data = useMemo<{ nodes: FGNode[]; links: FGLink[] }>(
    () => ({ nodes: nodes.map((n) => ({ ...n })), links: links.map((l) => ({ ...l })) }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally keyed on shape, not array identity
    [topoSig],
  );

  // Spread nodes out so edges overlap less: stronger repulsion + longer links than
  // the d3 defaults. Re-applied whenever the graph changes, then fit to view once.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force('charge')?.strength(-160).distanceMax(400);
    fg.d3Force('link')?.distance(55);
    fitNext.current = true;
    fg.d3ReheatSimulation();
  }, [data]);

  // Re-run the layout on demand. Force layouts settle stochastically, so we re-seed
  // node positions (a plain reheat barely moves) to get a genuinely different, and
  // hopefully less tangled, arrangement — then fit to view when it settles.
  const relayout = () => {
    const fg = fgRef.current;
    if (!fg) return;
    for (const n of data.nodes) {
      n.x = (Math.random() - 0.5) * 100;
      n.y = (Math.random() - 0.5) * 100;
      n.vx = 0;
      n.vy = 0;
    }
    fitNext.current = true;
    fg.d3ReheatSimulation();
  };

  const endpointId = (v: unknown): string => (typeof v === 'object' && v ? (v as { id: string }).id : (v as string));
  // A link is "incident" to the focused node when that node is one of its endpoints.
  // After the force sim resolves, l.source/l.target become node objects, so normalise via endpointId.
  const isIncident = (l: { source: unknown; target: unknown }): boolean =>
    !!selectedId && (endpointId(l.source) === selectedId || endpointId(l.target) === selectedId);

  // Fan parallel edges (same node pair) apart so overlapping relationships — e.g. a
  // "partner" and a "competitor" edge between the same two companies — render as
  // separate arcs instead of stacking on one line. Single edges stay straight.
  const curvature = useMemo(() => {
    const key = (l: ViewLink) => `${l.source}|${l.target}|${l.type}`;
    const groups = new Map<string, ViewLink[]>();
    for (const l of links) {
      const pair = l.source <= l.target ? `${l.source}|${l.target}` : `${l.target}|${l.source}`;
      const arr = groups.get(pair);
      if (arr) arr.push(l); else groups.set(pair, [l]);
    }
    const MAXC = 0.3;
    const map = new Map<string, number>();
    for (const arr of groups.values()) {
      if (arr.length === 1) { map.set(key(arr[0]), 0); continue; }
      const lastIdx = arr.length - 1;
      map.set(key(arr[lastIdx]), MAXC);
      const delta = (2 * MAXC) / lastIdx;
      for (let i = 0; i < lastIdx; i++) {
        let c = -MAXC + i * delta;
        if (arr[lastIdx].source !== arr[i].source) c *= -1;   // flip when the edge runs the other way
        map.set(key(arr[i]), c);
      }
    }
    return map;
  }, [links]);
  const localXY = (e: MouseEvent) => {
    const r = wrap.current?.getBoundingClientRect();
    return { x: e.clientX - (r?.left ?? 0), y: e.clientY - (r?.top ?? 0) };
  };

  // Centre (and zoom into) the node the find box picked. Positions live on the
  // force-sim's node copies; skip until assigned. Keyed on the request only —
  // later data changes must not re-pan to an old pick.
  useEffect(() => {
    if (!focus) return;
    const fg = fgRef.current;
    const n = data.nodes.find((x) => x.id === focus.id);
    if (!fg || !n || typeof n.x !== 'number' || typeof n.y !== 'number') return;
    fg.centerAt(n.x, n.y, 600);
    if (fg.zoom() < 2) fg.zoom(2, 600);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- camera command, not data sync
  }, [focus]);

  return (
    <div ref={wrap} className="graph-canvas" onContextMenu={(e) => e.preventDefault()}>
      <ForceGraph2D
        ref={fgRef}
        width={dims.width}
        height={dims.height}
        graphData={data}
        nodeRelSize={1}
        nodeVal={(n: FGNode) => nodeRadius(n.score) ** 2}
        nodeColor={(n: FGNode) => (n.external ? '#a96bff' : directionColor(n.direction))}
        nodeCanvasObjectMode={() => 'after'}
        nodeCanvasObject={(n: FGNode, ctx: CanvasRenderingContext2D, scale: number) => {
          const r = nodeRadius(n.score);
          const x = n.x ?? 0;
          const y = n.y ?? 0;
          if (n.id === selectedId) {                       // focus ring — fill (direction colour) stays intact
            ctx.beginPath();
            ctx.arc(x, y, r + 3 / scale, 0, 2 * Math.PI);
            ctx.lineWidth = 2.5 / scale;
            ctx.strokeStyle = '#ff2bd6';                   // neon magenta — distinct from every node state (incl. cyan HOLD)
            ctx.shadowColor = 'rgba(255, 43, 214, 0.9)';
            ctx.shadowBlur = 11 / scale;
            ctx.stroke();
            ctx.shadowBlur = 0;                            // reset so the label isn't blurred
          }
          ctx.fillStyle = '#eaf0ff';
          ctx.font = `${(n.id === selectedId ? 11 : 10) / scale}px "Exo 2", sans-serif`;
          ctx.textAlign = 'center';
          ctx.fillText(n.label, x, y - r - 2 / scale);
        }}
        linkColor={(l: FGLink) => (!selectedId || isIncident(l) ? sentimentColor(l.sentiment) : 'rgba(95, 110, 160, 0.16)')}
        linkWidth={(l: FGLink) => {
          const w = 0.5 + l.weight * l.confidence * 2;
          return selectedId && isIncident(l) ? w + 1.5 : w;   // emphasise the focused node's edges
        }}
        linkCurvature={(l: FGLink) => curvature.get(`${endpointId(l.source)}|${endpointId(l.target)}|${l.type}`) ?? 0}
        linkLineDash={(l: FGLink) => (l.origin === 'imported' ? [6, 3] : l.origin === 'manual' ? [1.5, 3.5] : [])}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkLabel={(l: FGLink) => `${l.type} · ${l.sentiment}${l.evidence ? ` · ${l.evidence}` : ''}`}
        onEngineStop={() => {
          if (fitNext.current) { fitNext.current = false; fgRef.current?.zoomToFit(400, 40); }
        }}
        onNodeClick={(n: FGNode) => { setMenu(null); onSelect(String(n.id)); }}
        onBackgroundClick={() => { setMenu(null); onBackgroundClick(); }}
        onLinkClick={() => setMenu(null)}
        onNodeRightClick={(n: FGNode, e: MouseEvent) => {
          e.preventDefault();
          const id = String(n.id);
          const items: MenuItem[] = [
            { label: 'Add company…', onClick: onAddCompany },
            { label: 'Add relationship', onClick: () => onAddRelationship(id) },
            { label: 'Rename node…', onClick: () => onRenameNode(id) },
          ];
          if (!id.includes(':')) {
            items.push(watchlist.includes(id)
              ? { label: `★ Remove ${id} from watchlist`, onClick: () => onToggleWatch(id) }
              : { label: `☆ Add ${id} to watchlist`, onClick: () => onToggleWatch(id) });
          }
          items.push({ label: 'Delete node', danger: true, onClick: () => onDeleteNode(id) });
          setMenu({ ...localXY(e), items });
        }}
        onBackgroundRightClick={(e: MouseEvent) => {
          e.preventDefault();
          setMenu({ ...localXY(e), items: [{ label: 'Add company…', onClick: onAddCompany }] });
        }}
        onLinkRightClick={(l: FGLink, e: MouseEvent) => {
          e.preventDefault();
          const ref = { source: endpointId(l.source), target: endpointId(l.target), type: l.type as RelationType };
          setMenu({ ...localXY(e), items: [{ label: 'Delete relationship', danger: true, onClick: () => onDeleteEdge(ref) }] });
        }}
      />
      <GraphLegend />
      <button
        type="button"
        className="graph-relayout"
        onClick={relayout}
        title="Re-run the layout to reduce overlapping edges"
      >
        ⟳ Re-layout
      </button>
      {menu && <GraphContextMenu items={menu.items} x={menu.x} y={menu.y} onClose={() => setMenu(null)} />}
    </div>
  );
}
