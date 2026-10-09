// Keyset-paged lists (backend `Page[T]`): one envelope, merged client-side.
import type { InfiniteData } from '@tanstack/react-query';

/** Backend `Page[T]`: `next_cursor` is null (or absent) on the last page. */
export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}

/** `getNextPageParam` for `useInfiniteQuery`: undefined ends the list. */
export function nextCursor<T>(page: Page<T>): string | undefined {
  return page.next_cursor ?? undefined;
}

type Pages<T> = Pick<InfiniteData<Page<T>, unknown>, 'pages'>;

const byId = (row: unknown): unknown => (row as { id?: unknown }).id;

/** Flattens loaded pages in order. A row that reappears on a later page (the
 * list was refetched after inserts) keeps its first position. */
export function mergePages<T>(data: Pages<T> | undefined, keyOf: (row: T) => unknown = byId): T[] {
  if (!data) return [];
  const seen = new Set<unknown>();
  const rows: T[] = [];
  for (const page of data.pages) {
    for (const row of page.items) {
      const key = keyOf(row);
      if (key !== undefined && seen.has(key)) continue;
      seen.add(key);
      rows.push(row);
    }
  }
  return rows;
}
