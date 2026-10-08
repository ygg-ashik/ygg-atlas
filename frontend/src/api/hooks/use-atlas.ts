import { useQuery } from '@tanstack/react-query';
import { fetchMetricsCatalog } from '../atlas';

/** The governed catalog changes only on deploy, so cache it generously. */
export function useMetricsCatalog() {
  return useQuery({
    queryKey: ['atlas-metrics'],
    queryFn: fetchMetricsCatalog,
    staleTime: 5 * 60_000,
  });
}
