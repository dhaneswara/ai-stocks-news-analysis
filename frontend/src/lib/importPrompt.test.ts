import { describe, expect, it } from 'vitest';
import { chatGptPrompt } from './importPrompt';

describe('chatGptPrompt', () => {
  it('injects the company and keeps the JSON contract', () => {
    const p = chatGptPrompt('NVDA');
    expect(p).toContain('NVDA');
    expect(p).toContain('"nodes"');
    expect(p).toContain('"edges"');
    expect(p).toContain('supplier|customer|partner|competitor|owner|subsidiary|other');
  });
  it('falls back to a placeholder when empty', () => {
    expect(chatGptPrompt('')).toContain('[COMPANY]');
  });
});
