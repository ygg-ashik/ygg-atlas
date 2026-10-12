// src/lib/routes.ts
// The one source of truth for UI routes. Route definitions (App.tsx), the
// navigation, and every link or navigate call read these, so a page moves in
// one place. Backend API paths (`/api/v1/...`) are not UI routes and live in `api/`.

/** Every UI route; `:id` patterns are for the router, the builders fill them. */
export const ROUTES = {
  home: '/',
  login: '/login',
  consent: '/oauth/consent',
  ask: '/ask',
  /** The chat route: a draft, or one thread. */
  askThread: '/ask/:sessionId?',
  metrics: '/metrics',
  /** Settings › General. */
  settings: '/settings',
  access: '/settings/access',
  requests: '/settings/requests',
  newRequest: '/settings/requests/new',
  tokens: '/settings/tokens',
  adminUsers: '/settings/admin/users',
  adminUser: '/settings/admin/users/:id',
  adminGroups: '/settings/admin/groups',
  adminGroup: '/settings/admin/groups/:id',
  adminRequests: '/settings/admin/requests',
  adminAudit: '/settings/admin/audit',
  adminTokens: '/settings/admin/tokens',
  adminClients: '/settings/admin/clients',
} as const;

export type RequestKindPrefill = 'group' | 'role' | 'resource';

/** What a request link or dialog starts from (all optional). */
export interface RequestPrefill {
  kind?: RequestKindPrefill;
  /** A catalog path, e.g. `demo/checkout/checkout_funnel`. */
  resource?: string;
  /** Its business label, e.g. "Checkout funnel". */
  label?: string;
}

const id = (value: string) => encodeURIComponent(value);

export const threadPath = (sessionId: string) => `${ROUTES.ask}/${id(sessionId)}`;
export const askPath = (question: string) => `${ROUTES.ask}?q=${encodeURIComponent(question)}`;
export const metricPath = (metricId: string) => `${ROUTES.metrics}#metric-${metricId}`;
export const adminUserPath = (userId: string) => `${ROUTES.adminUsers}/${id(userId)}`;
export const adminGroupPath = (groupId: string) => `${ROUTES.adminGroups}/${id(groupId)}`;

/** The new-request page with its prefill as query parameters. */
export function newRequestPath(prefill: RequestPrefill = {}): string {
  const params = new URLSearchParams();
  if (prefill.kind) params.set('kind', prefill.kind);
  if (prefill.resource) params.set('resource', prefill.resource);
  if (prefill.label) params.set('label', prefill.label);
  const query = params.toString();
  return query ? `${ROUTES.newRequest}?${query}` : ROUTES.newRequest;
}

/** A chat denial: request the exact resource it named. */
export const deniedRequestPath = (resource: string, label: string) =>
  newRequestPath({ resource, label });

/** The OAuth consent dead end (role without MCP access): request a role. */
export const consentRequestPath = () => newRequestPath({ kind: 'role' });

/** True on `/settings` and every page under it. */
export function isSettingsPath(pathname: string): boolean {
  return pathname === ROUTES.settings || pathname.startsWith(`${ROUTES.settings}/`);
}
