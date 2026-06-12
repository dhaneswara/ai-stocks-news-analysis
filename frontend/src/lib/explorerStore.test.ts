import { afterEach, describe, expect, it } from 'vitest';
import { clearExplorerState, loadExplorerState, saveExplorerState } from './explorerStore';
import type { KnowledgeGraph } from '../types';

const G: KnowledgeGraph = { as_of: 't', scope: 'company:AAPL', built: 1, skipped: 0, nodes: ['AAPL', 'TSM'], edges: [] };

afterEach(() => clearExplorerState());

describe('explorerStore', () => {
  it('returns null when nothing is stored', () => {
    expect(loadExplorerState()).toBeNull();
  });

  it('round-trips the explorer state through sessionStorage', () => {
    saveExplorerState({ working: G, root: 'AAPL', expanded: ['AAPL'], selectedId: 'AAPL', ontologyName: 'Tech' });
    const s = loadExplorerState();
    expect(s?.root).toBe('AAPL');
    expect(s?.working?.nodes).toEqual(['AAPL', 'TSM']);
    expect(s?.expanded).toEqual(['AAPL']);
    expect(s?.selectedId).toBe('AAPL');
    expect(s?.ontologyName).toBe('Tech');
  });

  it('clear removes the stored state', () => {
    saveExplorerState({ working: G, root: 'AAPL', expanded: [], selectedId: null, ontologyName: '' });
    clearExplorerState();
    expect(loadExplorerState()).toBeNull();
  });
});
