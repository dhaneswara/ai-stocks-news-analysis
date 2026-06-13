import { useState } from 'react';
import { useAddCustomCompany } from '../hooks/queries';

export function AddCompanyForm() {
  const [ticker, setTicker] = useState('');
  const add = useAddCustomCompany();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = ticker.trim();
    if (t) add.mutate(t);
  };

  return (
    <form className="add-company" onSubmit={submit}>
      <input
        value={ticker}
        onChange={(e) => setTicker(e.target.value)}
        placeholder="Add a company by ticker (e.g. ASML)…"
        title="Add a non-S&P 500 company — its name, exchange, sector and price are fetched automatically."
      />
      <button type="submit" disabled={add.isPending || !ticker.trim()}
              title="Fetch the company's details and add it to the Discover universe.">
        {add.isPending ? 'Adding…' : 'Add company'}
      </button>
      {add.isSuccess && (
        <span className="muted">
          ✓ Added {add.data.entry.name} ({add.data.entry.ticker}) · {add.data.entry.exchange || '—'} ·
          {' '}{add.data.entry.sector || '—'} · ${add.data.price.toFixed(2)}. Rescan to score it.
        </span>
      )}
      {add.isError && <span className="error">{(add.error as Error).message}</span>}
    </form>
  );
}
