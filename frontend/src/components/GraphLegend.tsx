import { useState } from 'react';

/** Collapsible legend overlaid in a corner of the graph canvas. */
export function GraphLegend() {
  const [open, setOpen] = useState(true);
  return (
    <div className="graph-legend-overlay">
      <button type="button" className="graph-legend-toggle" onClick={() => setOpen((o) => !o)}>
        Legend {open ? '▾' : '▸'}
      </button>
      {open && (
        <div className="graph-legend-body">
          <div className="legend-group">
            <span className="legend-title">Company</span>
            <span><i className="dot" style={{ background: '#3fb950' }} />buy</span>
            <span><i className="dot" style={{ background: '#f85149' }} />sell</span>
            <span><i className="dot" style={{ background: '#8b949e' }} />hold</span>
            <span><i className="dot" style={{ background: '#484f58' }} />unknown</span>
            <span><i className="dot" style={{ background: '#6e7681' }} />external</span>
            <span className="legend-note">size = score</span>
          </div>
          <div className="legend-group">
            <span className="legend-title">News effect</span>
            <span><i className="bar" style={{ background: '#3fb950' }} />positive</span>
            <span><i className="bar" style={{ background: '#f85149' }} />negative</span>
            <span><i className="bar" style={{ background: '#6e7681' }} />neutral</span>
          </div>
          <div className="legend-group">
            <span className="legend-title">Source</span>
            <span><i className="line solid" />news</span>
            <span><i className="line dashed" />imported</span>
            <span><i className="line dotted" />manual</span>
          </div>
        </div>
      )}
    </div>
  );
}
