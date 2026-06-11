import { describe, expect, it } from 'vitest';
import { usMarketStatus } from './marketClock';

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
