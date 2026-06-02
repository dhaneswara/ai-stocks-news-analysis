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
      height: 420,
      layout: { background: { type: ColorType.Solid, color: '#0b0d12' }, textColor: '#d8dce5' },
      grid: { vertLines: { color: '#1c212c' }, horzLines: { color: '#1c212c' } },
      rightPriceScale: { borderColor: '#262c39' },
      timeScale: { borderColor: '#262c39' },
    });

    const candles = chart.addCandlestickSeries({
      upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
      wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    });
    candles.setData(
      data.candles.map((c) => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })),
    );

    if (data.indicators.sma50.length) {
      const s = chart.addLineSeries({ color: '#f0b90b', lineWidth: 1, priceLineVisible: false });
      s.setData(data.indicators.sma50.map((p) => ({ time: p.time, value: p.value })));
    }
    if (data.indicators.sma200.length) {
      const s = chart.addLineSeries({ color: '#4c8dff', lineWidth: 1, priceLineVisible: false });
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
