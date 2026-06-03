import { useEffect, useRef } from 'react';
import { ColorType, createChart, type IChartApi } from 'lightweight-charts';
import type { Signal, StockData } from '../types';
import { signalsToMarkers } from '../lib/markers';

export function PriceChart({
  data,
  signals,
  onSelectSignal,
}: {
  data: StockData;
  signals: Signal[];
  onSelectSignal?: (s: Signal) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart: IChartApi = createChart(el, {
      autoSize: true,
      height: 360,
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

    const candles = chart.addCandlestickSeries({
      upColor: '#5fd39b', downColor: '#f0817c', borderVisible: false,
      wickUpColor: '#5fd39b', wickDownColor: '#f0817c',
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
      })),
    );

    if (onSelectSignal) {
      chart.subscribeClick((param) => {
        const t = param.time as unknown as string | undefined;
        if (!t) return;
        const hit = signals.find((s) => s.date === t);
        if (hit) onSelectSignal(hit);
      });
    }

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data, signals, onSelectSignal]);

  return <div ref={containerRef} className="price-chart" />;
}
