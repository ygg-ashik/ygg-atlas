import { useQuery } from '@tanstack/react-query';
import { fetchCapabilityCatalog } from '../access';
import { queryKeys } from '../query-keys';

/** Capabilities and roles change only on deploy. */
export function useCapabilityCatalog() {
  return useQuery({
    queryKey: queryKeys.capabilities,
    queryFn: fetchCapabilityCatalog,
    staleTime: 30 * 60_000,
  });
}
