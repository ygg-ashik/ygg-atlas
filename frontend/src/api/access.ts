// The caller's own access (GET /me/access) and the capability catalog
// (GET /meta/capabilities). Shapes: backend app/access/schemas/.
import { api } from './axios-instance';

export type GroupStanding = 'member' | 'manager';

export interface GroupRef {
  id: string;
  name: string;
  standing: GroupStanding;
}

/** `MeAccessOut`. */
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
  /** Field clearance codes the caller holds (e.g. `fields:people_names`). */
  clearances: string[];
}

export interface CapabilityInfo {
  code: string;
  description: string;
}

export interface RoleInfo {
  name: string;
  capabilities: string[];
}

/** `ClearanceOut`: a field clearance a grant can give. */
export interface ClearanceInfo {
  code: string;
  description: string;
}

/** `CatalogOut`. `label_classes` is the whole YAML vocabulary (it includes
 * `category`, which is never masked); the classes an admin may set come from
 * `GET /admin/label-classes`, never from this list. */
export interface CapabilityCatalog {
  capabilities: CapabilityInfo[];
  roles: RoleInfo[];
  clearances: ClearanceInfo[];
  label_classes: string[];
  mask_modes: string[];
}

export async function fetchMyAccess(): Promise<MeAccess> {
  const { data } = await api.get<MeAccess>('/me/access');
  return data;
}

export async function fetchCapabilityCatalog(): Promise<CapabilityCatalog> {
  const { data } = await api.get<CapabilityCatalog>('/meta/capabilities');
  return data;
}
