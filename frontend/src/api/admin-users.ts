// Users and per-user effective access (admin:users). Shapes: backend
// app/access/schemas/users.py; user list and detail.
import { type GrantOut, type RowScope } from './admin-groups';
import { api } from './axios-instance';
import { type Page } from './cursor';
import { compactParams, seg } from './params';

export type UserStatus = 'active' | 'disabled';
export type UserKind = 'human' | 'service';

/** `UserOut`. */
export interface User {
  id: string;
  email: string;
  display_name: string;
  kind: string;
  role: string;
  status: string;
  last_seen_at: string | null;
  created_at: string;
}

export interface UserGroup {
  id: string;
  name: string;
  standing: string;
}

/** `UserDetailOut = UserOut + {groups, direct_grants, pending_requests}`. */
export interface UserDetail extends User {
  groups: UserGroup[];
  direct_grants: GrantOut[];
  pending_requests: number;
}

/** `GET /admin/users` filters. Empty values are not sent. */
export interface UserFilters {
  q?: string;
  role?: string;
  status?: UserStatus;
  kind?: UserKind;
}

/** `UserUpdate`: only the fields sent change. */
export interface UserUpdate {
  role?: string;
  status?: UserStatus;
}

/** `RuleOut`. `row_scope` null = all rows; `$self` is already resolved. */
export interface Rule {
  pattern: string;
  grant_id: string;
  origin: string;
  row_scope: RowScope | null;
}

/** `SkippedOut`: a grant the evaluator ignored (e.g. a malformed or
 * unresolvable row scope), with why. */
export interface SkippedRule {
  pattern: string;
  grant_id: string;
  origin: string;
  reason: string;
}

/** `DecisionOut`. `row_scope`: null = all rows; otherwise the alternatives,
 * ORed; `[]` = no rows. The atlas may narrow it further, never widen it. */
export interface ResourceDecision {
  resource: string;
  allowed: boolean;
  reason: string;
  row_scope: RowScope[] | null;
}

/** `EffectiveAccessOut`; `clearances` is empty for a disabled user. */
export interface EffectiveAccess {
  user_id: string;
  role: string;
  active: boolean;
  capabilities: string[];
  allow: Rule[];
  deny: Rule[];
  decision: ResourceDecision | null;
  clearances: string[];
  skipped: SkippedRule[];
}

export interface UserPageRequest {
  filters?: UserFilters;
  cursor?: string;
  limit?: number;
}

export async function listUsers({ filters = {}, cursor, limit }: UserPageRequest = {}) {
  const params = compactParams({ ...filters, cursor, limit });
  const { data } = await api.get<Page<User>>('/admin/users', { params });
  return data;
}

export async function fetchUserDetail(userId: string): Promise<UserDetail> {
  const { data } = await api.get<UserDetail>(`/admin/users/${seg(userId)}`);
  return data;
}

export async function updateUser(userId: string, body: UserUpdate): Promise<User> {
  const { data } = await api.patch<User>(`/admin/users/${seg(userId)}`, body);
  return data;
}

/** The target's effective access; with `resource`, also its decision for that path. */
export async function fetchEffectiveAccess(
  userId: string,
  resource?: string,
): Promise<EffectiveAccess> {
  const params = compactParams({ resource });
  const { data } = await api.get<EffectiveAccess>(`/admin/users/${seg(userId)}/access`, {
    params,
  });
  return data;
}
