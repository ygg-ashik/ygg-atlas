import { QueryClient } from '@tanstack/react-query';

/** Shared TanStack Query client with conservative defaults for an internal
 * chat app: no focus refetch, short retry, 5-minute freshness. */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 1000 * 60 * 5,
    },
  },
});
