/** US-market session clock for the "when should I run this?" hint.
 *
 * The app currently covers S&P 500 stocks only, so the close that matters is the US
 * regular session (9:30–16:00 America/New_York, Mon–Fri). All math is done through
 * Intl with the IANA zone, so DST is handled and the result renders in the USER's
 * local timezone. Half-days and US market holidays are not modeled — the hint is
 * guidance, not a trading calendar. Add per-market entries here if the app ever
 * expands beyond US listings.
 */

const NY = 'America/New_York';
const OPEN_MIN = 9 * 60 + 30;
const CLOSE_MIN = 16 * 60;
const WEEKDAYS = new Set(['Mon', 'Tue', 'Wed', 'Thu', 'Fri']);
const DAY_MS = 24 * 3_600_000;

interface NyParts {
  weekday: string;
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

function nyParts(d: Date): NyParts {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: NY, weekday: 'short', year: 'numeric', month: 'numeric',
    day: 'numeric', hour: 'numeric', minute: 'numeric', hour12: false,
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? '';
  return {
    weekday: get('weekday'),
    year: Number(get('year')),
    month: Number(get('month')),
    day: Number(get('day')),
    hour: Number(get('hour')) % 24, // hour12:false can yield "24" at midnight
    minute: Number(get('minute')),
  };
}

/** 16:00 New York on the given NY calendar date, as an exact instant. */
function closeOnNyDate(year: number, month: number, day: number): Date {
  let t = new Date(Date.UTC(year, month - 1, day, 20, 0)); // 16:00 if EDT (UTC-4)
  const adjust = 16 - nyParts(t).hour; // 0 in EDT, +1 in EST
  if (adjust !== 0) t = new Date(t.getTime() + adjust * 3_600_000);
  return t;
}

export interface MarketStatus {
  /** Regular US session in progress right now (holidays not modeled). */
  open: boolean;
  /** The next 16:00-New-York close as an exact instant. */
  nextClose: Date;
  /** The user's IANA timezone, e.g. "Asia/Singapore". */
  tz: string;
  /** nextClose rendered in the user's locale + timezone, e.g. "Fri 4:00 AM". */
  nextCloseLabel: string;
}

export function usMarketStatus(now: Date = new Date()): MarketStatus {
  const p = nyParts(now);
  const minutes = p.hour * 60 + p.minute;
  const open = WEEKDAYS.has(p.weekday) && minutes >= OPEN_MIN && minutes < CLOSE_MIN;

  let candidate = closeOnNyDate(p.year, p.month, p.day);
  for (let i = 0; i < 7; i++) {
    const inPast = candidate.getTime() <= now.getTime();
    const onWeekend = !WEEKDAYS.has(nyParts(candidate).weekday);
    if (!inPast && !onWeekend) break;
    const next = nyParts(new Date(candidate.getTime() + DAY_MS));
    candidate = closeOnNyDate(next.year, next.month, next.day);
  }

  return {
    open,
    nextClose: candidate,
    tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    nextCloseLabel: candidate.toLocaleString(undefined, {
      weekday: 'short', hour: 'numeric', minute: '2-digit',
    }),
  };
}
