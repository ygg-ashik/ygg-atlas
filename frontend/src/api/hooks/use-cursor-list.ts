import { useInfiniteQuery, type QueryKey } from '@tanstack/react-query';
import { useMemo } from 'react';
import { mergePages, nextCursor, type Page } from '../cursor';

export interface CursorListOptions {
  enabled?: boolean;
}

/** A keyset-paged list: `fetchNextPage()` follows `next_cursor`; `items` is
 * every loaded page merged in order. */
export function useCursorList<T>(
  queryKey: QueryKey,
  fetchPage: (cursor: string | undefined) => Promise<Page<T>>,
  { enabled = true }: CursorListOptions = {},
) {
  const query = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) => fetchPage(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: nextCursor<T>,
    enabled,
  });
  const items = useMemo(() => mergePages(query.data), [query.data]);
  return { ...query, items };
}
