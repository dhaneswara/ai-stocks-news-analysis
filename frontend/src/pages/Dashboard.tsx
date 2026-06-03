import { useEffect, useState } from 'react';
import { PriceChart, type ChartRange } from '../components/PriceChart';
import { IndicatorBar } from '../components/IndicatorBar';
import { NewsList } from '../components/NewsList';
import { ReasoningPanel } from '../components/ReasoningPanel';
import { SignalList } from '../components/SignalList';
import { TickerBar } from '../components/TickerBar';
import { useAnalyze, useSettings, useStock } from '../hooks/queries';
import type { AnalysisResult, Signal } from '../types';

const RANGES: ChartRange[] = ['1M', '3M', '6M', '1Y', '2Y', '5Y'];
// Each chart range maps to the yfinance period the LLM analyzes over.
const RANGE_TO_PERIOD: Record<ChartRange, string> = {
  '1M': '1mo', '3M': '3mo', '6M': '6mo', '1Y': '1y', '2Y': '2y', '5Y': '5y',
};

export default function Dashboard() {
  const settings = useSettings();
  const watchlist = settings.data?.watchlist ?? [];
  const [ticker, setTicker] = useState('');
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [selected, setSelected] = useState<Signal | null>(null);
  const [range, setRange] = useState<ChartRange>('2Y');

  const stock = useStock(ticker);
  const analyze = useAnalyze(ticker, RANGE_TO_PERIOD[range]);

  // Default to the first watchlist ticker once settings load.
  useEffect(() => {
    if (!ticker && watchlist.length) setTicker(watchlist[0]);
  }, [watchlist, ticker]);

  // Reset analysis when the ticker changes.
  useEffect(() => {
    setAnalysis(null);
    setSelected(null);
  }, [ticker]);

  const runAnalyze = () => {
    analyze.mutate(undefined, {
      onSuccess: (res) => {
        setSelected(null);
        setAnalysis(res);
      },
    });
  };

  const d = stock.data;
  const up = d ? d.price.change >= 0 : false;
  const sign = up ? '+' : '';

  return (
    <>
      <div className="panel commandbar">
        <TickerBar
          watchlist={watchlist}
          onSelect={setTicker}
          onAnalyze={runAnalyze}
          analyzing={analyze.isPending}
          canAnalyze={!!stock.data}
        />
      </div>

      {!ticker && <p className="muted">Enter a ticker or pick one from your watchlist to begin.</p>}
      {stock.isLoading && <p className="muted">Loading {ticker}…</p>}
      {stock.isError && <p className="error">Could not load {ticker}: {(stock.error as Error).message}</p>}
      {analyze.isError && <p className="error">Analysis failed: {(analyze.error as Error).message}</p>}

      {d && (
        <>
          <section className="panel summary">
            <div className="summary-id">
              <span className="section-label">{d.ticker} · {d.price.currency} · {d.as_of}</span>
              <h1 className="hero-name">{d.company_name}</h1>
              <div className="hero-quote">
                <span className="hero-price">
                  <span className="cur">{d.price.currency === 'USD' ? '$' : ''}</span>
                  {d.price.current.toFixed(2)}
                </span>
                <span className={`hero-change ${up ? 'up' : 'down'}`}>
                  <span className="arrow">{up ? '▲' : '▼'}</span>
                  {sign}{d.price.change.toFixed(2)} ({sign}{d.price.change_pct.toFixed(2)}%)
                </span>
              </div>
            </div>
            <div className="summary-stats">
              <IndicatorBar data={d} />
            </div>
          </section>

          <div className="workspace">
            <section className="panel chart-panel">
              <div className="panel-head">
                <div className="range-tabs">
                  {RANGES.map((r) => (
                    <button
                      key={r}
                      className={`range-tab${r === range ? ' active' : ''}`}
                      onClick={() => setRange(r)}
                    >
                      {r}
                    </button>
                  ))}
                </div>
                <span className="legend">
                  <span><i className="dot" style={{ background: '#e8c87e' }} />SMA 50</span>
                  <span><i className="dot" style={{ background: '#9c8246' }} />SMA 200</span>
                </span>
              </div>
              <PriceChart data={d} signals={analysis?.signals ?? []} range={range} onSelectSignal={setSelected} />
              {analysis && <p className="hint">Click a marker — or a signal in Analysis — to read its reasoning.</p>}
            </section>

            <section className="panel analysis">
              <div className="panel-head">
                <span className="section-label">Analysis</span>
              </div>
              {analysis ? (
                <div className="analysis-scroll"><ReasoningPanel result={analysis} /></div>
              ) : (
                <p className="muted">Click “Analyze with LLM” to generate a reasoned recommendation and buy/sell signals drawn on the chart.</p>
              )}
            </section>

            <aside className="side-col">
              <section className="panel signals-col">
                <div className="panel-head">
                  <span className="section-label">Signals — click for reasoning</span>
                </div>
                {analysis ? (
                  <div className="signals-scroll">
                    <SignalList signals={analysis.signals} selected={selected} onSelect={setSelected} />
                  </div>
                ) : (
                  <p className="muted">Run an analysis to see buy/sell signals here.</p>
                )}
              </section>
              <section className="panel news-col">
                <div className="panel-head">
                  <span className="section-label">News</span>
                </div>
                <div className="news-scroll"><NewsList news={d.news} /></div>
              </section>
            </aside>
          </div>
        </>
      )}
    </>
  );
}
