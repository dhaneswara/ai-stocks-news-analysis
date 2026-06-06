import { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { directionColor, nodeRadius, sentimentColor, type ViewLink, type ViewNode } from '../lib/graphView';

export interface GraphCanvasProps {
  nodes: ViewNode[];
  links: ViewLink[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function GraphCanvas({ nodes, links, selectedId, onSelect }: GraphCanvasProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ width: 600, height: 480 });

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) =>
      setDims({ width: entry.contentRect.width, height: entry.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Stable graphData (keyed on nodes/links, NOT selection) so selecting a node
  // recolours without restarting the force simulation.
  const data = useMemo(
    () => ({ nodes: nodes.map((n) => ({ ...n })), links: links.map((l) => ({ ...l })) }),
    [nodes, links],
  );

  const neighbours = useMemo(() => {
    const set = new Set<string>();
    if (selectedId) {
      for (const l of links) {
        if (l.source === selectedId) set.add(l.target);
        if (l.target === selectedId) set.add(l.source);
      }
    }
    return set;
  }, [links, selectedId]);

  const isDim = (id: string) => !!selectedId && id !== selectedId && !neighbours.has(id);

  return (
    <div ref={wrap} className="graph-canvas">
      <ForceGraph2D
        width={dims.width}
        height={dims.height}
        graphData={data}
        nodeRelSize={1}
        nodeVal={(n: any) => nodeRadius(n.score) ** 2}
        nodeColor={(n: any) => (isDim(n.id) ? '#30363d' : directionColor(n.direction))}
        nodeCanvasObjectMode={() => 'after'}
        nodeCanvasObject={(n: any, ctx: CanvasRenderingContext2D, scale: number) => {
          ctx.fillStyle = isDim(n.id) ? '#6e7681' : '#e6edf3';
          ctx.font = `${10 / scale}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.fillText(n.label, n.x, n.y - nodeRadius(n.score) - 2 / scale);
        }}
        linkColor={(l: any) => sentimentColor(l.sentiment)}
        linkWidth={(l: any) => 0.5 + l.weight * l.confidence * 2}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkLabel={(l: any) => `${l.type} · ${l.sentiment}${l.evidence ? ` · ${l.evidence}` : ''}`}
        onNodeClick={(n: any) => onSelect(n.id)}
      />
    </div>
  );
}
