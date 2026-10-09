// The caller's own access (GET /me/access) and the capability catalog
// (GET /meta/capabilities). Shapes: backend app/access/schemas.py.
import { api } from './axios-instance';

export type GroupStanding = 'member' | 'manager';

export interface GroupRef {
  id: string;
  name: string;
  standing: GroupStanding;
}

/** `MeAccessOut`. The identity and count fields arrive with phase 5 (B5);
 * `clearances` arrives with phase 3 and is absent until then. */
export interface MeAccess {
  role: string;
  capabilities: string[];
  groups: GroupRef[];
  has_data_access: boolean;
  user_id: string;
  email: string;
  display_name: string;
  /** The caller's own pending requests. */
  pending_requests: number;
  /** Requests the caller may decide, never their own (backend `decidable_scope`). */
  pending_approvals: number;
  is_manager: boolean;
  clearances?: string[];
}

export interface CapabilityInfo {
  code: string;
  description: string;
}

export interface RoleInfo {
  name: string;
  capabilities: string[];
}

/** `CatalogOut`. `clearances`, `label_classes` and `mask_modes` arrive with phase 3. */
export interface CapabilityCatalog {
  capabilities: CapabilityInfo[];
  roles: RoleInfo[];
  clearances?: CapabilityInfo[];
  label_classes?: string[];
  mask_modes?: string[];
}

export async function fetchMyAccess(): Promise<MeAccess> {
  const { data } = await api.get<MeAccess>('/me/access');
  return data;
}

export async function fetchCapabilityCatalog(): Promise<CapabilityCatalog> {
  const { data } = await api.get<CapabilityCatalog>('/meta/capabilities');
  return data;
}
