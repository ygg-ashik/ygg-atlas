import { useQuery } from '@tanstack/react-query';
import { fetchCatalogResources } from '../catalog-admin';
import { queryKeys } from '../query-keys';

/** Catalog metadata for the grant picker; with `asUser`, that user's
 * decision on every entity and item (the preview). */
export function useCatalogResources(asUser: string | null = null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.catalogResources(asUser),
    queryFn: () => fetchCatalogResources(asUser ?? undefined),
    staleTime: asUser ? 30_000 : 5 * 60_000,
    enabled,
  });
}
