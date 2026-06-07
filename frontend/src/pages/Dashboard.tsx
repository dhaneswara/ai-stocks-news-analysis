import { useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PriceChart, type ChartRange } from '../components/PriceChart';
import { IndicatorBar } from '../components/IndicatorBar';
import { NewsList } from '../components/NewsList';
import { ReasoningPanel } from '../components/ReasoningPanel';
import { SignalList } from '../components/SignalList';
import { TickerBar } from '../components/TickerBar';
import { ScoreChip } from '../components/ScoreChip';
import { useAnalyze, useScore, useStock, useWatchlist } from '../hooks/queries';
import { useDashboardState } from '../state/dashboardState';

const RANGES: ChartRange[] = ['1M', '3M', '6M', '1Y', '2Y', '5Y'];
// Each chart range maps to the yfinance period the LLM analyzes over.
const RANGE_TO_PERIOD: Record<ChartRange, string> = {
  '1M': '1mo', '3M': '3mo', '6M': '6mo', '1Y': '1y', '2Y': '2y', '5Y': '5y',
};

export default function Dashboard() {
  const watch = useWatchlist();
  const watchlist = watch.list;
  const [searchParams] = useSearchParams();
  const urlTicker = (searchParams.get('ticker') ?? '').toUpperCase();
  // View-state lives in a provider above the router so it survives navigating to
  // Discover/Settings and back — the route unmounts, but this state does not.
  const { ticker, setTicker, range, setRange, analysis, setAnalysis, selected, setSelected } =
    useDashboardState();

  const stock = useStock(ticker);
  const score = useScore(ticker);
  const analyze = useAnalyze(ticker, RANGE_TO_PERIOD[range]);

  // Select the ticker from a ?ticker= deep-link (e.g. clicked from the Discover board).
  useEffect(() => {
    if (urlTicker) setTicker(urlTicker);
  }, [urlTicker, setTicker]);

  // Default to the first watchlist ticker once settings load.
  useEffect(() => {
    if (!ticker && watchlist.length) setTicker(watchlist[0]);
  }, [watchlist, ticker, setTicker]);

  // Reset the analysis only when the ticker ACTUALLY changes — not on every mount.
  // (On remount the ref re-initialises to the current ticker, so returning from
  // another page keeps the persisted analysis instead of clearing it.)
  const prevTicker = useRef(ticker);
  useEffect(() => {
    if (prevTicker.current === ticker) return;
    prevTicker.current = ticker;
    setAnalysis(null);
    setSelected(null);
  }, [ticker, setAnalysis, setSelected]);

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
          current={ticker}
          onSelect={setTicker}
          onAdd={watch.add}
          onRemove={watch.remove}
          onAnalyze={runAnalyze}
          analyzing={analyze.isPending}
          canAnalyze={!!stock.data}
        />
      </div>

      {!ticker && <p className="muted">Enter a ticker or pick one from your watchlist to begin.</p>}
      {stock.isLoading && <p className="muted">Loading {ticker}…</p>}
      {stock.isError && <p className="error">Could not load {ticker}: {(stock.error as Error).message}</p>}
      {analyze.isError && <p className="error">Analysis failed: {(analyze.error as Error).message}</p>}
      {watch.isError && <p className="error">Couldn't update watchlist: {(watch.error as Error).message}</p>}

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
              {score.data && <ScoreChip score={score.data} />}
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
