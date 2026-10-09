// Shared pieces of the audit tabs: option pickers, the UTC date range, the
// list states (skeleton, failure, "Load more") and the collapsed JSON view.
import type * as React from 'react';
import {
  Button,
  DateField,
  ErrorNotice,
  isIsoDate,
  Select,
  SkeletonRegion,
  SkeletonRows,
} from '@/ui';

export interface PickOption {
  value: string;
  label: string;
}

interface PickProps {
  label: string;
  value: string;
  options: readonly PickOption[];
  onChange: (value: string) => void;
}

/** A native select whose empty value means "any". */
export function Pick({ label, value, options, onChange }: PickProps) {
  return (
    <Select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{label}: any</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </Select>
  );
}

/** Plain string options (actions, object types, surfaces). */
export const plainOptions = (values: readonly string[]): PickOption[] =>
  values.map((value) => ({ value, label: value }));

/** Distinct options seen in the loaded rows, plus the selected one (kept so a
 * filtered list can still show and clear it). */
export function seenOptions<T>(
  rows: readonly T[],
  pick: (row: T) => PickOption | null,
  selected: PickOption | null,
): PickOption[] {
  const byValue = new Map<string, PickOption>();
  if (selected) byValue.set(selected.value, selected);
  for (const row of rows) {
    const option = pick(row);
    if (option && !byValue.has(option.value)) byValue.set(option.value, option);
  }
  return [...byValue.values()].sort((a, b) => a.label.localeCompare(b.label));
}

export interface DateRange {
  from: string;
  to: string;
}

export const NO_RANGE: DateRange = { from: '', to: '' };

const nextDay = (iso: string) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
};

/** The API's `since` (inclusive) and `until` (exclusive) for whole UTC days;
 * a date that isn't complete and real yet is not sent. */
export function rangeQuery({ from, to }: DateRange): { since?: string; until?: string } {
  const out: { since?: string; until?: string } = {};
  if (isIsoDate(from)) out.since = `${from}T00:00:00Z`;
  if (isIsoDate(to)) out.until = `${nextDay(to)}T00:00:00Z`;
  return out;
}

export function DateRangeFields({
  value,
  onChange,
}: {
  value: DateRange;
  onChange: (value: DateRange) => void;
}) {
  return (
    <>
      <DateField
        aria-label="From (UTC)"
        placeholder="From YYYY-MM-DD"
        value={value.from}
        onChange={(e) => onChange({ ...value, from: e.target.value })}
      />
      <DateField
        aria-label="To (UTC)"
        placeholder="To YYYY-MM-DD"
        value={value.to}
        onChange={(e) => onChange({ ...value, to: e.target.value })}
      />
    </>
  );
}

interface PagedQuery {
  isPending: boolean;
  isError: boolean;
  isFetching: boolean;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  refetch: () => unknown;
  fetchNextPage: () => unknown;
}

/** Skeleton while the first page loads, a stated failure with Retry, else the
 * list followed by "Load more" while the keyset has another page. */
export function PagedBody({
  query,
  what,
  children,
}: {
  query: PagedQuery;
  /** "the change log" — names the skeleton and the failure. */
  what: string;
  children: React.ReactNode;
}) {
  if (query.isPending) {
    return (
      <SkeletonRegion label={what} className="rounded-card bg-card px-[18px] py-3.5">
        <SkeletonRows count={6} />
      </SkeletonRegion>
    );
  }
  if (query.isError) {
    return (
      <ErrorNotice
        title={`Couldn't load ${what}`}
        onRetry={() => void query.refetch()}
        retrying={query.isFetching}
      >
        The access service didn&apos;t answer. Nothing changed.
      </ErrorNotice>
    );
  }
  return (
    <>
      {children}
      {query.hasNextPage && (
        <div className="mt-3.5 flex justify-center">
          <Button
            variant="pill"
            onClick={() => void query.fetchNextPage()}
            disabled={query.isFetchingNextPage}
          >
            {query.isFetchingNextPage ? 'Loading…' : 'Load more'}
          </Button>
        </div>
      )}
    </>
  );
}

/** Raw JSON (tool arguments, event details), collapsed until asked for. */
export function JsonDetails({ label, value }: { label: string; value: unknown }) {
  return (
    <details className="text-caption text-muted-foreground">
      <summary className="cursor-pointer select-none">{label}</summary>
      <pre className="mt-1.5 overflow-x-auto whitespace-pre rounded-sm bg-card px-2.5 py-2 font-mono text-xs text-body">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}
