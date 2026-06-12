import type { KnowledgeGraph } from '../types';

export interface ExplorerState {
  working: KnowledgeGraph | null;
  root: string;
  expanded: string[];
  selectedId: string | null;
  ontologyName: string;
}

const KEY = 'graphExplorer:v1';

/** Restore the last exploration from sessionStorage (survives menu switches + reload within the tab). */
export function loadExplorerState(): ExplorerState | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as ExplorerState) : null;
  } catch {
    return null; // storage unavailable / corrupt — start fresh
  }
}

export function saveExplorerState(state: ExplorerState): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    /* storage unavailable / quota — non-fatal */
  }
}

export function clearExplorerState(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* non-fatal */
  }
}
