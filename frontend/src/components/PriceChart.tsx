import { useEffect, useRef } from 'react';
import { ColorType, createChart, type IChartApi } from 'lightweight-charts';
import type { Signal, StockData } from '../types';
import { signalsToMarkers } from '../lib/markers';

export type ChartRange = '1M' | '3M' | '6M' | '1Y' | '2Y' | '5Y';

// Calendar-days lookback per range. 5Y (≈ full fetched history) falls back to fitContent.
const RANGE_DAYS: Record<ChartRange, number | null> = {
  '1M': 30,
  '3M': 91,
  '6M': 182,
  '1Y': 365,
  '2Y': 730,
  '5Y': null,
};

// Zoom the visible window to the selected range without refetching/rebuilding.
function applyRange(chart: IChartApi, candles: StockData['candles'], range: ChartRange) {
  const ts = chart.timeScale();
  const days = RANGE_DAYS[range];
  const first = candles[0]?.time;
  const last = candles[candles.length - 1]?.time;
  if (!days || !first || !last) {
    ts.fitContent();
    return;
  }
  const d = new Date(`${last}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  const from = d.toISOString().slice(0, 10);
  if (from <= (first as string)) {
    ts.fitContent();
    return;
  }
  try {
    ts.setVisibleRange({ from, to: last });
  } catch {
    ts.fitContent();
  }
}

export function PriceChart({
  data,
  signals,
  range = '1Y',
  onSelectSignal,
}: {
  data: StockData;
  signals: Signal[];
  range?: ChartRange;
  onSelectSignal?: (s: Signal) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart: IChartApi = createChart(el, {
      autoSize: true,
      height: 406,
      layout: {
        background: { type: ColorType.Solid, color: '#0b0b0d' },
        textColor: '#8b8780',
        fontFamily: '"IBM Plex Mono", ui-monospace, monospace',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(244,241,234,0.04)' },
        horzLines: { color: 'rgba(244,241,234,0.045)' },
      },
      rightPriceScale: { borderColor: 'rgba(244,241,234,0.09)' },
      timeScale: { borderColor: 'rgba(244,241,234,0.09)' },
      crosshair: {
        vertLine: { color: 'rgba(232,200,126,0.40)', width: 1, labelBackgroundColor: '#caa86a' },
        horzLine: { color: 'rgba(232,200,126,0.40)', width: 1, labelBackgroundColor: '#caa86a' },
      },
    });
    chartRef.current = chart;

    const candles = chart.addCandlestickSeries({
      // Slightly muted candle bodies so the vivid buy/sell markers stand out.
      upColor: '#3f9d77', downColor: '#cf6f6a', borderVisible: false,
      wickUpColor: '#3f9d77', wickDownColor: '#cf6f6a',
    });
    candles.setData(
      data.candles.map((c) => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })),
    );

    if (data.indicators.sma50.length) {
      const s = chart.addLineSeries({ color: '#e8c87e', lineWidth: 2, priceLineVisible: false, crosshairMarkerVisible: false });
      s.setData(data.indicators.sma50.map((p) => ({ time: p.time, value: p.value })));
    }
    if (data.indicators.sma200.length) {
      const s = chart.addLineSeries({ color: '#9c8246', lineWidth: 2, priceLineVisible: false, crosshairMarkerVisible: false });
      s.setData(data.indicators.sma200.map((p) => ({ time: p.time, value: p.value })));
    }

    candles.setMarkers(
      signalsToMarkers(signals).map((m) => ({
        time: m.time,
        position: m.position,
        color: m.color,
        shape: m.shape,
        text: m.text,
        size: 2,
      })),
    );

    if (onSelectSignal) {
      chart.subscribeClick((param) => {
        if (!param.point || signals.length === 0) return;
        // Pick the nearest marker by horizontal pixel distance — forgiving, and
        // independent of zoom — instead of demanding an exact-date click.
        const tscale = chart.timeScale();
        let best: Signal | null = null;
        let bestDist = Infinity;
        for (const s of signals) {
          const x = tscale.timeToCoordinate(s.date);
          if (x === null) continue;
          const dist = Math.abs(x - param.point.x);
          if (dist < bestDist) {
            bestDist = dist;
            best = s;
          }
        }
        if (best && bestDist <= 28) onSelectSignal(best);
      });
    }

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [data, signals, onSelectSignal]);

  // Apply the selected window — re-applying on resize AND after the chart is rebuilt.
  // The build effect above recreates the chart whenever `signals` change (e.g. clicking
  // "Analyze with LLM"), and a fresh chart defaults to showing all history — so `signals`
  // is in this effect's deps to re-zoom to `range` after that rebuild. Effects run in
  // declaration order, so the rebuilt chart already exists in chartRef when this runs.
  // (Re-applying on resize is also what makes the range stick once autoSize has measured
  // the flex-sized container — the first setVisibleRange runs before the chart has
  // dimensions and is otherwise ignored.)
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const apply = () => {
      if (chartRef.current) applyRange(chartRef.current, data.candles, range);
    };
    apply();
    const ro = new ResizeObserver(() => apply());
    ro.observe(el);
    return () => ro.disconnect();
  }, [range, data, signals]);

  return <div ref={containerRef} className="price-chart" />;
}
