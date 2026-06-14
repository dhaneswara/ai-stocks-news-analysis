import { useState } from 'react';
import { PALETTES, useTheme } from '../lib/theme';

/** Collapsible legend overlaid in a corner of the graph canvas. */
export function GraphLegend() {
  const [open, setOpen] = useState(true);
  const p = PALETTES[useTheme().theme];
  return (
    <div className="graph-legend-overlay">
      <button type="button" className="graph-legend-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        Legend {open ? '▾' : '▸'}
      </button>
      {open && (
        <div className="graph-legend-body">
          <div className="legend-group">
            <span className="legend-title">Company</span>
            <span><i className="dot" style={{ background: p.nodeBuy }} />buy</span>
            <span><i className="dot" style={{ background: p.nodeSell }} />sell</span>
            <span><i className="dot" style={{ background: p.nodeHold }} />hold</span>
            <span><i className="dot" style={{ background: p.nodeUnknown }} />unknown</span>
            <span><i className="dot" style={{ background: p.nodeExternal }} />external</span>
            <span><i className="dot" style={{ background: 'transparent', border: `2px solid ${p.focusRing}`, boxSizing: 'border-box' }} />selected</span>
            <span className="legend-note">size = score</span>
          </div>
          <div className="legend-group">
            <span className="legend-title">Line colour · news effect</span>
            <span><i className="bar" style={{ background: p.sentimentPos }} />positive</span>
            <span><i className="bar" style={{ background: p.sentimentNeg }} />negative</span>
            <span><i className="bar" style={{ background: p.sentimentNeutral }} />neutral</span>
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
