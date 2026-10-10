import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../query-keys';
import { listCredentialEvents, type CredentialEventFilters } from '../tokens';

/** Token and client lifecycle events (phase 4), newest first; one page of
 * `limit` rows (the route has no cursor). */
export function useCredentialEvents(filters: CredentialEventFilters = {}, enabled = true) {
  return useQuery({
    queryKey: queryKeys.credentialEvents(filters),
    queryFn: () => listCredentialEvents(filters),
    enabled,
  });
}
