import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { fetchOverview, type OverviewDays } from '../overview';

/** keepPreviousData: switching range morphs values instead of flashing a skeleton. */
export function useOverview(days: OverviewDays) {
  return useQuery({
    queryKey: ['atlas-overview', days],
    queryFn: () => fetchOverview(days),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}
