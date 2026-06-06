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

  it('getGraph GETs /graph with scope', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ nodes: [], edges: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.getGraph('focus');
    expect(fetchMock.mock.calls[0][0] as string).toContain('/graph?scope=focus');
  });

  it('rebuildGraph POSTs /graph/rebuild', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ nodes: [], edges: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    await api.rebuildGraph();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url as string).toContain('/graph/rebuild');
    expect((init as RequestInit).method).toBe('POST');
  });
});
