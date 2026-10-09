import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../query-keys';
import { listCredentialEvents, type CredentialEventFilters } from '../tokens';

/** Token and client lifecycle events (phase 4). `data.available === false`
 * until phase 4 ships: the Credentials tab shows "Not available yet". */
export function useCredentialEvents(filters: CredentialEventFilters = {}, enabled = true) {
  return useQuery({
    queryKey: queryKeys.credentialEvents(filters),
    queryFn: () => listCredentialEvents(filters),
    enabled,
  });
}
