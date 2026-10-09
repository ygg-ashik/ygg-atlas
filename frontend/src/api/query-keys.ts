// Every access-shaped TanStack Query key, in one place. Keys are hierarchical
// so a write can invalidate a whole family by prefix (e.g. ['admin','users']).
import { type RequestStatusFilter } from './access-requests';
import { type SubjectType } from './admin-groups';
import { type UserFilters } from './admin-users';
import { type ChangeFilters, type DecisionFilters, type SummaryDays } from './audit';
import { type AdminTokenFilters, type CredentialEventFilters } from './tokens';

export const queryKeys = {
  /** The caller's access; a 409 on any write invalidates it. */
  myAccess: ['me', 'access'] as const,
  myRequests: ['me', 'requests'] as const,
  myRequestList: ['me', 'requests', 'list'] as const,
  requestOptions: (resource: string) => ['me', 'requests', 'options', resource] as const,
  myTokens: ['me', 'tokens'] as const,
  connectedApps: ['me', 'connected-apps'] as const,

  capabilities: ['meta', 'capabilities'] as const,
  authMethods: ['meta', 'auth-methods'] as const,
  scopeDimensions: ['meta', 'scope-dimensions'] as const,

  /** Prefix of every admin view: an access write invalidates all of them. */
  admin: ['admin'] as const,
  users: ['admin', 'users'] as const,
  userList: (filters: UserFilters) => ['admin', 'users', 'list', filters] as const,
  userDetail: (userId: string) => ['admin', 'users', 'detail', userId] as const,
  userAccess: (userId: string, resource: string | null) =>
    ['admin', 'users', 'access', userId, resource] as const,
  userAttributes: (userId: string) => ['admin', 'users', 'attributes', userId] as const,

  groups: ['admin', 'groups'] as const,
  groupList: ['admin', 'groups', 'list'] as const,
  groupDetail: (groupId: string) => ['admin', 'groups', 'detail', groupId] as const,
  groupMembers: (groupId: string) => ['admin', 'groups', 'members', groupId] as const,
  memberCandidates: (groupId: string, q: string) =>
    ['admin', 'groups', 'candidates', groupId, q] as const,

  grants: ['admin', 'grants'] as const,
  grantList: (subjectType: SubjectType, subjectId: string) =>
    ['admin', 'grants', subjectType, subjectId] as const,

  requestQueue: ['admin', 'requests'] as const,
  requestQueueList: (status: RequestStatusFilter, userId: string | null = null) =>
    ['admin', 'requests', status, userId] as const,

  audit: ['admin', 'audit'] as const,
  changes: (filters: ChangeFilters) => ['admin', 'audit', 'changes', filters] as const,
  decisions: (filters: DecisionFilters) => ['admin', 'audit', 'decisions', filters] as const,
  auditSummary: (days: SummaryDays) => ['admin', 'audit', 'summary', days] as const,
  credentialEvents: (filters: CredentialEventFilters) =>
    ['admin', 'audit', 'credentials', filters] as const,

  labelClasses: ['admin', 'label-classes'] as const,
  catalogResources: (asUser: string | null) => ['admin', 'catalog-resources', asUser] as const,
  adminTokens: ['admin', 'tokens'] as const,
  adminTokenList: (filters: AdminTokenFilters) => ['admin', 'tokens', filters] as const,
  clients: ['admin', 'clients'] as const,
} as const;
