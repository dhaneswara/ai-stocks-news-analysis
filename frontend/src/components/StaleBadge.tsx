import { isStale } from '../lib/marketClock';

/** Render the `YYYY-MM-DD` bar date as `Jun 12, 2026`, anchored at UTC noon so the local
 * timezone never shifts it to the day before/after. */
function prettyBarDate(ymd: string): string {
  return new Date(`${ymd}T12:00:00Z`).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
  });
}

/** A small amber pill shown when a ticker's latest price bar is behind the most recent completed
 * US trading day — i.e. the data provider hasn't published a newer daily close yet (see
 * `lib/marketClock`). Renders nothing when the data is current or absent. */
export function StaleBadge({ lastDate }: { lastDate: string | null | undefined }) {
  if (!isStale(lastDate)) return null;
  return (
    <span
      className="stale-badge"
      title={`Latest price bar is ${prettyBarDate(lastDate!)} — the data provider hasn't published a newer close yet. Re-scan later.`}
    >
      ⚠ Data lagging
    </span>
  );
}
