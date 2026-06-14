import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_THEME,
  PALETTES,
  applyTheme,
  getTheme,
  readStoredTheme,
} from './theme';

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
  applyTheme(DEFAULT_THEME); // reset module state between tests
  localStorage.clear();
});

describe('readStoredTheme', () => {
  it('defaults to gold when nothing is stored', () => {
    localStorage.clear();
    expect(readStoredTheme()).toBe('gold');
    expect(DEFAULT_THEME).toBe('gold');
  });

  it('returns a valid stored theme', () => {
    localStorage.setItem('mc-theme', 'neon');
    expect(readStoredTheme()).toBe('neon');
  });

  it('falls back to gold for an invalid stored value', () => {
    localStorage.setItem('mc-theme', 'banana');
    expect(readStoredTheme()).toBe('gold');
  });

  it('falls back to gold when localStorage throws', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(readStoredTheme()).toBe('gold');
    spy.mockRestore();
  });
});

describe('applyTheme', () => {
  it('sets the html data-theme attribute, persists, and updates getTheme', () => {
    applyTheme('neon');
    expect(document.documentElement.getAttribute('data-theme')).toBe('neon');
    expect(localStorage.getItem('mc-theme')).toBe('neon');
    expect(getTheme()).toBe('neon');
  });

  it('does not throw when localStorage.setItem throws', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(() => applyTheme('gold')).not.toThrow();
    expect(document.documentElement.getAttribute('data-theme')).toBe('gold');
    spy.mockRestore();
  });
});

describe('PALETTES', () => {
  it('defines both themes with identical key sets', () => {
    const gold = Object.keys(PALETTES.gold).sort();
    const neon = Object.keys(PALETTES.neon).sort();
    expect(gold).toEqual(neon);
    expect(gold.length).toBeGreaterThan(0);
  });

  it('has distinct primary colors per theme', () => {
    expect(PALETTES.gold.sma50).not.toBe(PALETTES.neon.sma50);
    expect(PALETTES.gold.nodeHold).not.toBe(PALETTES.neon.nodeHold);
  });
});
