import { useEffect, useState } from 'react';
import { PriceChart } from '../components/PriceChart';
import { IndicatorBar } from '../components/IndicatorBar';
import { NewsList } from '../components/NewsList';
import { ReasoningPanel } from '../components/ReasoningPanel';
import { TickerBar } from '../components/TickerBar';
import { useAnalyze, useSettings, useStock } from '../hooks/queries';
import type { AnalysisResult, Signal } from '../types';

export default function Dashboard() {
  const settings = useSettings();
  const watchlist = settings.data?.watchlist ?? [];
  const [ticker, setTicker] = useState('');
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [selected, setSelected] = useState<Signal | null>(null);

  const stock = useStock(ticker);
  const analyze = useAnalyze(ticker);

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
    analyze.mutate(undefined, { onSuccess: (res) => setAnalysis(res) });
  };

  return (
    <>
      <div className="panel">
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

      {stock.data && (
        <>
          <div className="panel">
            <h3 style={{ marginTop: 0 }}>{stock.data.company_name} ({stock.data.ticker})</h3>
            <IndicatorBar data={stock.data} />
          </div>

          <div className="panel">
            <PriceChart data={stock.data} signals={analysis?.signals ?? []} onSelectSignal={setSelected} />
            {analysis && <p className="muted" style={{ fontSize: 12 }}>Click a ▲/▼ marker to see its reasoning.</p>}
          </div>

          <div className="row">
            <div className="panel">
              <h3 style={{ marginTop: 0 }}>Analysis</h3>
              {analysis ? (
                <ReasoningPanel result={analysis} selected={selected} />
              ) : (
                <p className="muted">Click "Analyze with LLM" to generate a reasoned recommendation and buy/sell signals.</p>
              )}
            </div>
            <div className="panel">
              <h3 style={{ marginTop: 0 }}>News</h3>
              <NewsList news={stock.data.news} />
            </div>
          </div>
        </>
      )}
    </>
  );
}
