import { describe, expect, it } from 'vitest';
import { llmPrompt } from './importPrompt';

describe('llmPrompt', () => {
  const NOW = new Date('2026-06-13T00:00:00Z');

  it('injects the company and keeps the JSON contract', () => {
    const p = llmPrompt('NVDA', { now: NOW });
    expect(p).toContain('NVDA');
    expect(p).toContain('"nodes"');
    expect(p).toContain('"edges"');
    expect(p).toContain('supplier|customer|partner|competitor|owner|subsidiary|other');
  });

  it('states today (with year) and a window derived from recencyDays', () => {
    const p = llmPrompt('NVDA', { now: NOW, recencyDays: 30 });
    expect(p).toContain('2026-06-13');   // today, includes the current year
    expect(p).toContain('2026-05-14');   // 30 days earlier
    expect(p).toContain('30 days');
    expect(p).toContain('"as_of": "2026-06-13"');
  });

  it('defaults to a 90-day window', () => {
    const p = llmPrompt('NVDA', { now: NOW });
    expect(p).toContain('2026-03-15');   // 90 days before 2026-06-13
    expect(p).toContain('90 days');
  });

  it('falls back to a placeholder when empty', () => {
    expect(llmPrompt('', { now: NOW })).toContain('[COMPANY]');
  });
});
