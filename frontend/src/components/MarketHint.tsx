import { usMarketStatus } from '../lib/marketClock';

/** When-to-run guidance for any surface that records calls against daily candles
 *  (Evaluation processes, Discover rescans, Dashboard analyses): the honest moment is
 *  after the US close, shown in the user's own timezone.
 *
 *  `quiet` renders nothing while the market is closed — for busy pages where only the
 *  "you're about to record partial-day prices" caution is worth space. */
export function MarketHint({ quiet = false }: { quiet?: boolean }) {
  const m = usMarketStatus();
  if (quiet && !m.open) return null;
  const explain =
    'Calls are recorded against the day’s candle, and the LLM batches record once per '
    + 'trading day — run after the US close (4:00 PM New York, regular sessions; '
    + 'holidays not modeled) so prices are final.';
  return (
    <p className="muted" title={explain}>
      {m.open
        ? `⏳ US market is open — today's prices are still partial. Best run after the close: ${m.nextCloseLabel} (${m.tz}).`
        : `✓ US market is closed — daily prices are final, a good time to run. Next close: ${m.nextCloseLabel} (${m.tz}).`}
    </p>
  );
}
