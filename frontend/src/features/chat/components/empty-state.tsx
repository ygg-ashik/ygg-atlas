import { Orbit } from 'lucide-react';

export function EmptyState({
  starters,
  onPick,
}: {
  starters: string[];
  onPick: (text: string) => void;
}) {
  return (
    <div className="mt-16 text-center">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent text-accent-foreground">
        <Orbit className="h-6 w-6" />
      </div>
      <h2 className="text-lg font-semibold tracking-tight">Ask the atlas</h2>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
        Revenue, orders, funnels, campaigns — answered from governed metric definitions. Every
        number carries provenance.
      </p>
      <div className="mx-auto mt-6 grid max-w-lg gap-2 sm:grid-cols-2">
        {starters.map((starter) => (
          <button
            key={starter}
            type="button"
            onClick={() => onPick(starter)}
            className="rounded-lg border bg-card px-3 py-2.5 text-left text-xs text-muted-foreground shadow-sm transition-colors hover:border-primary/40 hover:text-foreground"
          >
            {starter}
          </button>
        ))}
      </div>
    </div>
  );
}
