// Groups, memberships and grants (admin:groups, group managers for members).
// Shapes: backend app/access/schemas.py; detail and member role/status from B5.
import { api } from './axios-instance';
import { type GroupStanding } from './access';
import { seg } from './params';

/** Phase-3 row scope: dimension → allowed values (`$self` allowed). */
export type RowScope = Record<string, string[]>;

/** `GroupOut`. */
export interface Group {
  id: string;
  name: string;
  description: string;
  parent_id: string | null;
  created_at: string;
}

/** `GroupDetailOut = GroupOut + {member_count, grant_count, path}`; `path` is names, root first. */
export interface GroupDetail extends Group {
  member_count: number;
  grant_count: number;
  path: string[];
}

export interface GroupCreate {
  name: string;
  description?: string;
  parent_id?: string | null;
}

/** Only the fields sent change; `parent_id: null` makes a root group. */
export interface GroupUpdate {
  name?: string;
  description?: string;
  parent_id?: string | null;
}

/** `MemberOut`; `role` and `status` from B5. */
export interface Member {
  user_id: string;
  email: string;
  display_name: string;
  standing: GroupStanding;
  added_at: string;
  role: string;
  status: string;
}

export type SubjectType = 'group' | 'user';
export type GrantEffect = 'allow' | 'deny';
export type GrantTargetKind = 'resource' | 'capability' | 'clearance';

/** `GrantOut`; `row_scope` arrives with phase 3. */
export interface GrantOut {
  id: string;
  subject_type: SubjectType;
  subject_id: string;
  effect: GrantEffect;
  target_kind: GrantTargetKind;
  target: string;
  reason: string;
  expires_at: string | null;
  created_by: string | null;
  created_at: string;
  row_scope?: RowScope | null;
}

/** `GrantCreate`. Send `row_scope` only once phase 3 is live (resource allows only). */
export interface GrantCreate {
  subject_type: SubjectType;
  subject_id: string;
  effect?: GrantEffect;
  target_kind?: GrantTargetKind;
  target: string;
  reason?: string;
  expires_at?: string | null;
  row_scope?: RowScope | null;
}

export async function listGroups(): Promise<Group[]> {
  const { data } = await api.get<Group[]>('/admin/groups');
  return data;
}

export async function fetchGroupDetail(groupId: string): Promise<GroupDetail> {
  const { data } = await api.get<GroupDetail>(`/admin/groups/${seg(groupId)}`);
  return data;
}

export async function createGroup(body: GroupCreate): Promise<Group> {
  const { data } = await api.post<Group>('/admin/groups', body);
  return data;
}

export async function updateGroup(groupId: string, body: GroupUpdate): Promise<Group> {
  const { data } = await api.patch<Group>(`/admin/groups/${seg(groupId)}`, body);
  return data;
}

export async function deleteGroup(groupId: string): Promise<void> {
  await api.delete(`/admin/groups/${seg(groupId)}`);
}

export async function listMembers(groupId: string): Promise<Member[]> {
  const { data } = await api.get<Member[]>(`/admin/groups/${seg(groupId)}/members`);
  return data;
}

export async function putMember(
  groupId: string,
  userId: string,
  standing: GroupStanding = 'member',
): Promise<Member> {
  const { data } = await api.put<Member>(`/admin/groups/${seg(groupId)}/members/${seg(userId)}`, {
    standing,
  });
  return data;
}

export async function removeMember(groupId: string, userId: string): Promise<void> {
  await api.delete(`/admin/groups/${seg(groupId)}/members/${seg(userId)}`);
}

export async function listGrants(subjectType: SubjectType, subjectId: string) {
  const { data } = await api.get<GrantOut[]>('/admin/grants', {
    params: { subject_type: subjectType, subject_id: subjectId },
  });
  return data;
}

export async function createGrant(body: GrantCreate): Promise<GrantOut> {
  const { data } = await api.post<GrantOut>('/admin/grants', body);
  return data;
}

export async function revokeGrant(grantId: string): Promise<void> {
  await api.delete(`/admin/grants/${seg(grantId)}`);
}
