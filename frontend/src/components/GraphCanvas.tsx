import { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { directionColor, nodeRadius, sentimentColor, type ViewLink, type ViewNode } from '../lib/graphView';
import { GraphLegend } from './GraphLegend';
import { GraphContextMenu, type MenuItem } from './GraphContextMenu';
import type { RelationType } from '../types';

export interface GraphCanvasProps {
  nodes: ViewNode[];
  links: ViewLink[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onAddRelationship: (sourceId: string) => void;
  onAddCompany: () => void;
  onDeleteNode: (id: string) => void;
  onDeleteEdge: (ref: { source: string; target: string; type: RelationType }) => void;
  watchlist: string[];
  onToggleWatch: (id: string) => void;
}

interface Menu { x: number; y: number; items: MenuItem[] }

export function GraphCanvas({
  nodes, links, selectedId, onSelect, onAddRelationship, onAddCompany, onDeleteNode, onDeleteEdge,
  watchlist, onToggleWatch,
}: GraphCanvasProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const fgRef = useRef<any>(null);
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

  const data = useMemo(
    () => ({ nodes: nodes.map((n) => ({ ...n })), links: links.map((l) => ({ ...l })) }),
    [nodes, links],
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
    for (const n of data.nodes as any[]) {
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

  return (
    <div ref={wrap} className="graph-canvas" onContextMenu={(e) => e.preventDefault()}>
      <ForceGraph2D
        ref={fgRef}
        width={dims.width}
        height={dims.height}
        graphData={data}
        nodeRelSize={1}
        nodeVal={(n: any) => nodeRadius(n.score) ** 2}
        nodeColor={(n: any) => (n.external ? '#ab9df2' : directionColor(n.direction))}
        nodeCanvasObjectMode={() => 'after'}
        nodeCanvasObject={(n: any, ctx: CanvasRenderingContext2D, scale: number) => {
          const r = nodeRadius(n.score);
          if (n.id === selectedId) {                       // focus ring — fill (direction colour) stays intact
            ctx.beginPath();
            ctx.arc(n.x, n.y, r + 3 / scale, 0, 2 * Math.PI);
            ctx.lineWidth = 2 / scale;
            ctx.strokeStyle = '#e8c87e';                   // --gold
            ctx.shadowColor = 'rgba(232, 200, 126, 0.9)';
            ctx.shadowBlur = 8 / scale;
            ctx.stroke();
            ctx.shadowBlur = 0;                            // reset so the label isn't blurred
          }
          ctx.fillStyle = '#e6edf3';
          ctx.font = `${(n.id === selectedId ? 11 : 10) / scale}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.fillText(n.label, n.x, n.y - r - 2 / scale);
        }}
        linkColor={(l: any) => (!selectedId || isIncident(l) ? sentimentColor(l.sentiment) : 'rgba(110, 118, 129, 0.18)')}
        linkWidth={(l: any) => {
          const w = 0.5 + l.weight * l.confidence * 2;
          return selectedId && isIncident(l) ? w + 1.5 : w;   // emphasise the focused node's edges
        }}
        linkCurvature={(l: any) => curvature.get(`${endpointId(l.source)}|${endpointId(l.target)}|${l.type}`) ?? 0}
        linkLineDash={(l: any) => (l.origin === 'imported' ? [6, 3] : l.origin === 'manual' ? [1.5, 3.5] : [])}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkLabel={(l: any) => `${l.type} · ${l.sentiment}${l.evidence ? ` · ${l.evidence}` : ''}`}
        onEngineStop={() => {
          if (fitNext.current) { fitNext.current = false; fgRef.current?.zoomToFit(400, 40); }
        }}
        onNodeClick={(n: any) => onSelect(n.id)}
        onNodeRightClick={(n: any, e: MouseEvent) => {
          e.preventDefault();
          const items: MenuItem[] = [
            { label: 'Add company…', onClick: onAddCompany },
            { label: 'Add relationship', onClick: () => onAddRelationship(n.id) },
          ];
          if (!String(n.id).includes(':')) {
            items.push(watchlist.includes(n.id)
              ? { label: `★ Remove ${n.id} from watchlist`, onClick: () => onToggleWatch(n.id) }
              : { label: `☆ Add ${n.id} to watchlist`, onClick: () => onToggleWatch(n.id) });
          }
          items.push({ label: 'Delete node', danger: true, onClick: () => onDeleteNode(n.id) });
          setMenu({ ...localXY(e), items });
        }}
        onBackgroundRightClick={(e: MouseEvent) => {
          e.preventDefault();
          setMenu({ ...localXY(e), items: [{ label: 'Add company…', onClick: onAddCompany }] });
        }}
        onLinkRightClick={(l: any, e: MouseEvent) => {
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
