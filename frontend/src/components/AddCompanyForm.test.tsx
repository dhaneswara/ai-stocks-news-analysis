import { expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

vi.mock('../api/client', () => ({ api: { addCustomCompany: vi.fn(), listCustomCompanies: vi.fn(), deleteCustomCompany: vi.fn() } }));
import { api } from '../api/client';
import { AddCompanyForm } from './AddCompanyForm';

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => vi.clearAllMocks());

it('submits a ticker and shows the resolved company', async () => {
  vi.mocked(api.addCustomCompany).mockResolvedValue({
    entry: { ticker: 'PRIV', name: 'Private Co', sector: 'Tech', exchange: 'NYSE' }, price: 42.5,
  });
  wrap(<AddCompanyForm />);
  fireEvent.change(screen.getByPlaceholderText(/add a company/i), { target: { value: 'priv' } });
  fireEvent.click(screen.getByRole('button', { name: /add company/i }));
  await waitFor(() => expect(screen.getByText(/Private Co/)).toBeInTheDocument());
  expect(api.addCustomCompany).toHaveBeenCalledWith('priv');
});

it('shows the error from a rejected ticker', async () => {
  vi.mocked(api.addCustomCompany).mockRejectedValue(new Error("Could not add 'NOPE': No price history"));
  wrap(<AddCompanyForm />);
  fireEvent.change(screen.getByPlaceholderText(/add a company/i), { target: { value: 'NOPE' } });
  fireEvent.click(screen.getByRole('button', { name: /add company/i }));
  await waitFor(() => expect(screen.getByText(/No price history/)).toBeInTheDocument());
});
