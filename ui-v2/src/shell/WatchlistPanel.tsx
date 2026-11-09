export interface WatchlistPanelProps {
  symbols?: string[];
}

export function WatchlistPanel({ symbols = [] }: WatchlistPanelProps) {
  return (
    <section
      aria-labelledby="watchlist-heading"
      className="rounded-md border border-border bg-surface p-4"
    >
      <h2 id="watchlist-heading" className="mb-2 text-sm font-semibold text-text">
        Watchlist
      </h2>
      {symbols.length === 0 ? (
        <p className="text-sm text-text-muted">No symbols on the watchlist yet.</p>
      ) : (
        <ul className="space-y-1 text-sm text-text">
          {symbols.map((symbol) => (
            <li key={symbol}>{symbol}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
