import { useEffect, useRef } from 'react';

export interface MenuItem { label: string; onClick: () => void; danger?: boolean }
export interface GraphContextMenuProps { items: MenuItem[]; x: number; y: number; onClose: () => void }

/** A small right-click menu positioned at (x, y) inside the canvas; closes on outside-click / Escape. */
export function GraphContextMenu({ items, x, y, onClose }: GraphContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [onClose]);

  return (
    <div ref={ref} className="graph-ctx-menu" style={{ left: x, top: y }} role="menu">
      {items.map((it) => (
        <button
          key={it.label} type="button" role="menuitem"
          className={`graph-ctx-item${it.danger ? ' danger' : ''}`}
          onClick={() => { it.onClick(); onClose(); }}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}
