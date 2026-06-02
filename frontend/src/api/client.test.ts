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
});
