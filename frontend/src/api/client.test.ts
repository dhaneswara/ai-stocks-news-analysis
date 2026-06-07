import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './client';

afterEach(() => vi.unstubAllGlobals());

describe('api client', () => {
  it('GET stock parses JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ticker: 'AAPL' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const data = await api.getStock('AAPL');
    expect(data.ticker).toBe('AAPL');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/stock/AAPL?period=2y'),
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it('throws with backend detail on error response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, statusText: 'Bad', json: async () => ({ detail: 'No price history' }) }),
    );
    await expect(api.getStock('NOPE')).rejects.toThrow('No price history');
  });

  it('analyze POSTs', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ticker: 'AAPL' }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.analyze('AAPL');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/analyze/AAPL'),
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('getMood GETs /truth/mood', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ enabled: true, post_count: 2, mood: null }) });
    vi.stubGlobal('fetch', fetchMock);
    const body = await api.getMood();
    expect(body.post_count).toBe(2);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/truth/mood'), expect.any(Object));
  });

  it('getScreen builds a filtered query string', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.getScreen('Energy', 'buy', 10);
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/screen?');
    expect(url).toContain('sector=Energy');
    expect(url).toContain('direction=buy');
    expect(url).toContain('limit=10');
  });

  it('refreshUniverse POSTs /universe/refresh', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ count: 503, sectors: {}, source: 'x' }) });
    vi.stubGlobal('fetch', fetchMock);
    const body = await api.refreshUniverse();
    expect(body.count).toBe(503);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/universe/refresh');
    expect((init as RequestInit).method).toBe('POST');
  });

  it('getScreen sends limit=0 for "All"', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.getScreen(undefined, undefined, 0);
    expect(fetchMock.mock.calls[0][0] as string).toContain('limit=0');
  });

  it('getCompanyGraph GETs /graph/company/{ticker}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ nodes: ['AAPL'], edges: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.getCompanyGraph('AAPL');
    expect(fetchMock.mock.calls[0][0] as string).toContain('/graph/company/AAPL');
  });

  it('saveGraph POSTs /graph/saved with a body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ root: 'AAPL', saved_at: 't', expanded: [], graph: {} }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.saveGraph({ root: 'AAPL', saved_at: '', expanded: [], graph: { as_of: '', scope: 'x', nodes: [], edges: [], built: 0, skipped: 0 } });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url as string).toContain('/graph/saved');
    expect((init as RequestInit).method).toBe('POST');
  });

  it('listSavedGraphs GETs /graph/saved', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal('fetch', fetchMock);
    await api.listSavedGraphs();
    expect(fetchMock.mock.calls[0][0] as string).toMatch(/\/graph\/saved$/);
  });

  it('loadSavedGraph GETs a version when provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ root: 'AAPL', saved_at: 't', expanded: [], graph: {} }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.loadSavedGraph('AAPL', 't1');
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/graph/saved/AAPL');
    expect(url).toContain('version=t1');
  });

  it('deleteSavedGraph DELETEs /graph/saved/{root}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ deleted: true }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.deleteSavedGraph('AAPL');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url as string).toContain('/graph/saved/AAPL');
    expect((init as RequestInit).method).toBe('DELETE');
  });

  it('importGraph POSTs /graph/import with {name, payload}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 't', edges_added: 1 }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.importGraph('demo', { edges: [] });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url as string).toContain('/graph/import');
    expect((init as RequestInit).method).toBe('POST');
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ name: 'demo', payload: { edges: [] } });
  });

  it('listImports GETs /graph/imports', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal('fetch', fetchMock);
    await api.listImports();
    expect(fetchMock.mock.calls[0][0] as string).toMatch(/\/graph\/imports$/);
  });

  it('deleteImport DELETEs with set_id', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ deleted: true }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.deleteImport('2026-06-07T00:00:00+00:00');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url as string).toContain('/graph/imports?set_id=');
    expect(url as string).toContain('%3A'); // colon encoded
    expect((init as RequestInit).method).toBe('DELETE');
  });

  it('getScore GETs /score/{ticker}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ticker: 'AAPL', score: 72 }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.getScore('AAPL');
    expect(fetchMock.mock.calls[0][0] as string).toContain('/score/AAPL');
  });

  it('getImportSet GETs /graph/imports/{id} with the id encoded', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ scope: 'imported', edges: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.getImportSet('2026-06-07T00:00:00+00:00');
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/graph/imports/');
    expect(url).toContain('%3A'); // colon encoded
  });
});
