import { useEffect, useRef, useState } from 'react';

/** Collapsible, searchable watchlist. Replaces the inline chip row so a long watchlist stays
 *  one line. Click the toggle to open a filterable popover; pick a ticker to select (and close)
 *  or × to remove (stays open). Closes on Escape / outside-click. */
export function WatchlistMenu({ watchlist, current, onSelect, onRemove }: {
  watchlist: string[];
  current: string;
  onSelect: (ticker: string) => void;
  onRemove: (ticker: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const shown = watchlist.filter((t) => t.toUpperCase().includes(filter.trim().toUpperCase()));
  const select = (t: string) => { onSelect(t); setOpen(false); };

  return (
    <div className="watch-menu" ref={ref}>
      <button
        type="button"
        className="secondary watch-toggle"
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={watchlist.length === 0}
        onClick={() => setOpen((o) => !o)}
      >
        Watchlist ({watchlist.length}) {open ? '▴' : '▾'}
      </button>
      {open && (
        <div className="watch-pop" role="listbox">
          <input
            autoFocus
            className="watch-filter"
            placeholder="Filter…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <div className="watch-list">
            {shown.length === 0 && <p className="muted watch-empty">No matches</p>}
            {shown.map((t) => (
              <div
                key={t}
                role="option"
                aria-selected={t === current}
                className={`watch-item${t === current ? ' current' : ''}`}
                onClick={() => select(t)}
              >
                <span className="watch-item-label">{t}</span>
                <button
                  type="button"
                  className="chip-x"
                  aria-label={`Remove ${t}`}
                  onClick={(e) => { e.stopPropagation(); onRemove(t); }}
                >
                  {'×'}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
