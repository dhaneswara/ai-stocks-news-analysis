import type { StockData } from '../types';

function fmt(n: number | null | undefined, digits = 2): string {
  return n === null || n === undefined ? '—' : n.toFixed(digits);
}
function money(n: number | null): string {
  if (n === null) return '—';
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  return `${n}`;
}
function lastValue(points: { value: number }[]): number | null {
  return points.length ? points[points.length - 1].value : null;
}

export function IndicatorBar({ data }: { data: StockData }) {
  const rsi = lastValue(data.indicators.rsi14);
  const sma50 = lastValue(data.indicators.sma50);
  const sma200 = lastValue(data.indicators.sma200);
  // yfinance returns dividend_yield already as a percentage (e.g. 0.35 = 0.35%).
  const div = data.fundamentals.dividend_yield;
  return (
    <div className="metrics">
      <div className="metric"><div className="label">Price</div><div className="value">{fmt(data.price.current)}</div></div>
      <div className="metric"><div className="label">Change %</div><div className="value">{fmt(data.price.change_pct)}%</div></div>
      <div className="metric"><div className="label">RSI(14)</div><div className="value">{fmt(rsi)}</div></div>
      <div className="metric"><div className="label">SMA50</div><div className="value">{fmt(sma50)}</div></div>
      <div className="metric"><div className="label">SMA200</div><div className="value">{fmt(sma200)}</div></div>
      <div className="metric"><div className="label">52wk dist</div><div className="value">{fmt(data.indicators.dist_from_52wk_high_pct)}%</div></div>
      <div className="metric"><div className="label">P/E</div><div className="value">{fmt(data.fundamentals.pe_ratio)}</div></div>
      <div className="metric"><div className="label">Mkt cap</div><div className="value">{money(data.fundamentals.market_cap)}</div></div>
      <div className="metric"><div className="label">Div yield</div><div className="value">{div === null ? '—' : `${div.toFixed(2)}%`}</div></div>
    </div>
  );
}
