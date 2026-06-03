import { Fragment, useEffect, useRef } from 'react';
import type { Signal } from '../types';

export function SignalList({
  signals,
  selected,
  onSelect,
}: {
  signals: Signal[];
  selected: Signal | null;
  onSelect?: (s: Signal | null) => void;
}) {
  const reasonRef = useRef<HTMLDivElement>(null);

  // When a signal is picked (from here or the chart), reveal its reasoning.
  useEffect(() => {
    if (selected && reasonRef.current) {
      reasonRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [selected]);

  if (signals.length === 0) {
    return <p className="muted">No signals in this analysis.</p>;
  }

  return (
    <div className="signal-list">
      {signals.map((s, i) => {
        const isActive = selected === s;
        return (
          <Fragment key={`${s.date}-${i}`}>
            <button
              className={`signal-row ${s.action}${isActive ? ' active' : ''}`}
              aria-expanded={isActive}
              onClick={() => onSelect?.(isActive ? null : s)}
            >
              <span className="sig-arrow">{s.action === 'buy' ? '▲' : '▼'}</span>
              <span className="sig-act">{s.action.toUpperCase()}</span>
              <span className="sig-date">{s.date}</span>
              <span className="sig-price">{s.price.toFixed(2)}</span>
              <span className="sig-chev" aria-hidden="true">▾</span>
            </button>
            {isActive && (
              <div className="signal-reason" ref={reasonRef}>
                <div className="sig-head">
                  <span className={`badge ${s.action}`}>{s.action.toUpperCase()}</span>
                  <span>{s.date} @ {s.price} · confidence {(s.confidence * 100).toFixed(0)}%</span>
                </div>
                <p>{s.reasoning}</p>
              </div>
            )}
          </Fragment>
        );
      })}
    </div>
  );
}
