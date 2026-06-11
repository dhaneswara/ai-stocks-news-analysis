import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MarketHint } from './MarketHint';

vi.mock('../lib/marketClock', () => ({ usMarketStatus: vi.fn() }));

import { usMarketStatus } from '../lib/marketClock';

const CLOSED = {
  open: false, nextClose: new Date('2026-06-12T20:00:00Z'),
  tz: 'Asia/Singapore', nextCloseLabel: 'Sat 4:00 AM',
};
const OPEN = { ...CLOSED, open: true };

beforeEach(() => vi.mocked(usMarketStatus).mockReturnValue(CLOSED));

describe('MarketHint', () => {
  it('reassures when the market is closed, with the local next close', () => {
    render(<MarketHint />);
    expect(screen.getByText(/US market is closed/)).toBeInTheDocument();
    expect(screen.getByText(/Sat 4:00 AM \(Asia\/Singapore\)/)).toBeInTheDocument();
  });

  it('warns about partial prices while the market is open', () => {
    vi.mocked(usMarketStatus).mockReturnValue(OPEN);
    render(<MarketHint />);
    expect(screen.getByText(/US market is open/)).toBeInTheDocument();
    expect(screen.getByText(/still partial/)).toBeInTheDocument();
  });

  it('quiet mode renders nothing while closed', () => {
    const { container } = render(<MarketHint quiet />);
    expect(container).toBeEmptyDOMElement();
  });

  it('quiet mode still warns while open', () => {
    vi.mocked(usMarketStatus).mockReturnValue(OPEN);
    render(<MarketHint quiet />);
    expect(screen.getByText(/US market is open/)).toBeInTheDocument();
  });
});
