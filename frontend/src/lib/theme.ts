import { useSyncExternalStore } from 'react';

export type ThemeName = 'gold' | 'neon';
export const DEFAULT_THEME: ThemeName = 'gold';

const STORAGE_KEY = 'mc-theme';

/** Canvas-only colors (CSS surfaces are themed entirely in styles.css). */
export interface Palette {
  // price chart (lightweight-charts)
  chartBg: string;
  chartText: string;
  chartGridV: string;
  chartGridH: string;
  chartBorder: string;
  crosshair: string;
  crosshairLabel: string;
  candleUp: string;
  candleDown: string;
  sma50: string;
  sma200: string;
  markerBuy: string;
  markerSell: string;
  // knowledge graph (react-force-graph-2d canvas)
  nodeBuy: string;
  nodeSell: string;
  nodeHold: string;
  nodeUnknown: string;
  nodeExternal: string;
  focusRing: string;
  focusGlow: string;
  nodeLabel: string;
  sentimentPos: string;
  sentimentNeg: string;
  sentimentNeutral: string;
  fadedLink: string;
}

export const PALETTES: Record<ThemeName, Palette> = {
  gold: {
    chartBg: '#0b0b0d',
    chartText: '#8b8780',
    chartGridV: 'rgba(244,241,234,0.04)',
    chartGridH: 'rgba(244,241,234,0.045)',
    chartBorder: 'rgba(244,241,234,0.09)',
    crosshair: 'rgba(232,200,126,0.40)',
    crosshairLabel: '#caa86a',
    candleUp: '#3f9d77',
    candleDown: '#cf6f6a',
    sma50: '#e8c87e',
    sma200: '#9c8246',
    markerBuy: '#00e676',
    markerSell: '#ff5252',
    nodeBuy: '#3fb950',
    nodeSell: '#f85149',
    nodeHold: '#e8c87e',
    nodeUnknown: '#484f58',
    nodeExternal: '#ab9df2',
    focusRing: '#58a6ff',
    focusGlow: 'rgba(88, 166, 255, 0.9)',
    nodeLabel: '#e6edf3',
    sentimentPos: '#3fb950',
    sentimentNeg: '#f85149',
    sentimentNeutral: '#6e7681',
    fadedLink: 'rgba(110, 118, 129, 0.18)',
  },
  neon: {
    chartBg: '#08080f',
    chartText: '#7d8ab5',
    chartGridV: 'rgba(150,175,255,0.05)',
    chartGridH: 'rgba(150,175,255,0.055)',
    chartBorder: 'rgba(150,175,255,0.10)',
    crosshair: 'rgba(34,224,255,0.45)',
    crosshairLabel: '#0a93b8',
    candleUp: '#27c98b',
    candleDown: '#e0517a',
    sma50: '#22e0ff',
    sma200: '#a96bff',
    markerBuy: '#2bff9e',
    markerSell: '#ff3b6b',
    nodeBuy: '#2bff9e',
    nodeSell: '#ff3b6b',
    nodeHold: '#22e0ff',
    nodeUnknown: '#4a5280',
    nodeExternal: '#a96bff',
    focusRing: '#ff2bd6',
    focusGlow: 'rgba(255, 43, 214, 0.9)',
    nodeLabel: '#eaf0ff',
    sentimentPos: '#2bff9e',
    sentimentNeg: '#ff3b6b',
    sentimentNeutral: '#5f6b91',
    fadedLink: 'rgba(95, 110, 160, 0.16)',
  },
};

function isTheme(v: unknown): v is ThemeName {
  return v === 'gold' || v === 'neon';
}

export function readStoredTheme(): ThemeName {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return isTheme(v) ? v : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

let current: ThemeName = readStoredTheme();
const listeners = new Set<() => void>();

export function getTheme(): ThemeName {
  return current;
}

/** The ONE function that mutates global theme state. */
export function applyTheme(name: ThemeName): void {
  current = name;
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = name;
  }
  try {
    localStorage.setItem(STORAGE_KEY, name);
  } catch {
    /* private mode / blocked storage — keep the in-memory + DOM state */
  }
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function useTheme(): { theme: ThemeName; setTheme: (n: ThemeName) => void } {
  const theme = useSyncExternalStore(subscribe, getTheme, getTheme);
  return { theme, setTheme: applyTheme };
}
