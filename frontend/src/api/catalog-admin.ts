// Catalog metadata for the grant picker and the per-user preview
// (GET /atlas/catalog/resources, backend app/insights). Metadata only: no
// numbers, no data, no scope dimensions (those come from /meta/scope-dimensions).
import { api } from './axios-instance';
import { compactParams } from './params';

/** The target user's decision for one path; `origin` is "user", "group:<name>" or null. */
export interface CatalogDecision {
  allowed: boolean;
  reason: string;
  origin: string | null;
}

export interface CatalogItem {
  path: string;
  id: string;
  name: string;
  kind: 'metric' | 'funnel';
  decision?: CatalogDecision | null;
}

export interface CatalogEntity {
  path: string;
  name: string;
  items: CatalogItem[];
  decision?: CatalogDecision | null;
}

export interface CatalogResourceSource {
  id: string;
  name: string;
  entities: CatalogEntity[];
}

export interface CatalogResources {
  sources: CatalogResourceSource[];
  as_user?: string | null;
}

/** Without `asUser`: needs admin:users or admin:groups. With it: admin:users,
 * and every entity and item carries that user's decision. */
export async function fetchCatalogResources(asUser?: string): Promise<CatalogResources> {
  const { data } = await api.get<CatalogResources>('/atlas/catalog/resources', {
    params: compactParams({ as_user: asUser }),
  });
  return data;
}
