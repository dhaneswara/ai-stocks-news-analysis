import { useState } from 'react';

/** Collapsible legend overlaid in a corner of the graph canvas. */
export function GraphLegend() {
  const [open, setOpen] = useState(true);
  return (
    <div className="graph-legend-overlay">
      <button type="button" className="graph-legend-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        Legend {open ? '▾' : '▸'}
      </button>
      {open && (
        <div className="graph-legend-body">
          <div className="legend-group">
            <span className="legend-title">Company</span>
            <span><i className="dot" style={{ background: '#2bff9e' }} />buy</span>
            <span><i className="dot" style={{ background: '#ff3b6b' }} />sell</span>
            <span><i className="dot" style={{ background: '#22e0ff' }} />hold</span>
            <span><i className="dot" style={{ background: '#4a5280' }} />unknown</span>
            <span><i className="dot" style={{ background: '#a96bff' }} />external</span>
            <span><i className="dot" style={{ background: 'transparent', border: '2px solid #ff2bd6', boxSizing: 'border-box' }} />selected</span>
            <span className="legend-note">size = score</span>
          </div>
          <div className="legend-group">
            <span className="legend-title">Line colour · news effect</span>
            <span><i className="bar" style={{ background: '#2bff9e' }} />positive</span>
            <span><i className="bar" style={{ background: '#ff3b6b' }} />negative</span>
            <span><i className="bar" style={{ background: '#5f6b91' }} />neutral</span>
          </div>
          <div className="legend-group">
            <span className="legend-title">Line style · source</span>
            <span><i className="line solid" />news</span>
            <span><i className="line dashed" />imported</span>
            <span><i className="line dotted" />manual</span>
          </div>
        </div>
      )}
    </div>
  );
}
