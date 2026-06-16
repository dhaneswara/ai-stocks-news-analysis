import { describe, expect, it } from 'vitest';
import { isStale, latestTradingDay, usMarketStatus } from './marketClock';

// All fixtures assert on exact UTC instants so the tests pass regardless of the
// machine's locale or timezone. 16:00 New York = 20:00 UTC in EDT, 21:00 UTC in EST.
describe('usMarketStatus', () => {
  it('is open mid-session on a summer weekday (EDT)', () => {
    const s = usMarketStatus(new Date('2026-06-11T18:00:00Z')); // Thu 14:00 NY
    expect(s.open).toBe(true);
    expect(s.nextClose.toISOString()).toBe('2026-06-11T20:00:00.000Z');
  });

  it('is closed before the open; next close is the same day', () => {
    const s = usMarketStatus(new Date('2026-06-11T12:00:00Z')); // Thu 08:00 NY
    expect(s.open).toBe(false);
    expect(s.nextClose.toISOString()).toBe('2026-06-11T20:00:00.000Z');
  });

  it('is closed after hours; next close rolls to the next weekday', () => {
    const s = usMarketStatus(new Date('2026-06-11T21:00:00Z')); // Thu 17:00 NY
    expect(s.open).toBe(false);
    expect(s.nextClose.toISOString()).toBe('2026-06-12T20:00:00.000Z'); // Friday
  });

  it('weekends skip to Monday', () => {
    const s = usMarketStatus(new Date('2026-06-13T10:00:00Z')); // Saturday
    expect(s.open).toBe(false);
    expect(s.nextClose.toISOString()).toBe('2026-06-15T20:00:00.000Z'); // Monday
  });

  it('uses the EST offset in winter', () => {
    const s = usMarketStatus(new Date('2026-01-15T15:00:00Z')); // Thu 10:00 NY
    expect(s.open).toBe(true);
    expect(s.nextClose.toISOString()).toBe('2026-01-15T21:00:00.000Z');
  });

  it('crosses the autumn DST boundary correctly', () => {
    // Sat 2026-10-31; DST ends Sun 2026-11-01 → Monday's close is 16:00 EST = 21:00 UTC.
    const s = usMarketStatus(new Date('2026-10-31T12:00:00Z'));
    expect(s.open).toBe(false);
    expect(s.nextClose.toISOString()).toBe('2026-11-02T21:00:00.000Z');
  });

  it('reports the user timezone and a human label', () => {
    const s = usMarketStatus(new Date('2026-06-11T18:00:00Z'));
    expect(s.tz.length).toBeGreaterThan(0);
    expect(s.nextCloseLabel.length).toBeGreaterThan(0);
  });
});

// The candle dates the app stores are NY trading days; "latest completed trading day" is the
// most recent weekday strictly before today in New York. Fixtures pin exact UTC instants so the
// result is independent of the machine's locale/timezone.
describe('latestTradingDay', () => {
  it('returns the prior weekday on a normal weekday', () => {
    // Tue 2026-06-16 14:00 NY → Monday 2026-06-15
    expect(latestTradingDay(new Date('2026-06-16T18:00:00Z'))).toBe('2026-06-15');
  });

  it('returns the prior Friday on a Monday', () => {
    // Mon 2026-06-15 10:00 NY → Friday 2026-06-12 (skips the weekend)
    expect(latestTradingDay(new Date('2026-06-15T14:00:00Z'))).toBe('2026-06-12');
  });

  it('returns Friday on the weekend', () => {
    // Sat 2026-06-13 → Friday 2026-06-12
    expect(latestTradingDay(new Date('2026-06-13T14:00:00Z'))).toBe('2026-06-12');
    // Sun 2026-06-14 → Friday 2026-06-12
    expect(latestTradingDay(new Date('2026-06-14T14:00:00Z'))).toBe('2026-06-12');
  });

  it('uses the NY calendar date, not UTC, near the day boundary', () => {
    // 2026-06-16T02:00Z is still Mon 2026-06-15 22:00 in NY → strictly-prior weekday = Fri 06-12
    expect(latestTradingDay(new Date('2026-06-16T02:00:00Z'))).toBe('2026-06-12');
  });
});

describe('isStale', () => {
  const now = new Date('2026-06-16T18:00:00Z'); // Tue → latest completed trading day = 2026-06-15

  it('flags a bar behind the latest completed trading day', () => {
    expect(isStale('2026-06-12', now)).toBe(true); // SPCX: missing Mon 06-15
  });

  it('does not flag a bar that is the latest completed trading day', () => {
    expect(isStale('2026-06-15', now)).toBe(false);
  });

  it('does not flag a bar dated today', () => {
    expect(isStale('2026-06-16', now)).toBe(false);
  });

  it('is not stale when there is no bar', () => {
    expect(isStale(null, now)).toBe(false);
    expect(isStale(undefined, now)).toBe(false);
    expect(isStale('', now)).toBe(false);
  });
});
