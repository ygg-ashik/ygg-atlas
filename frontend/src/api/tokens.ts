// MCP credentials (phase 4): personal tokens, connected apps, admin token and
// client views, service accounts and credential events. Shapes: backend
// app/mcp/schemas.py. A deployment turns methods off through
// `/meta/auth-methods`, never by dropping routes; a missing or failed
// `/meta/auth-methods` reads as both methods disabled.
import { isAxiosError } from 'axios';
import { api } from './axios-instance';
import { compactParams, seg } from './params';

export type TokenKind = 'pat' | 'service' | 'oauth_access' | 'oauth_refresh';
/** `GET /admin/tokens?kind=`: `oauth` covers both OAuth kinds. */
export type TokenKindFilter = 'pat' | 'service' | 'oauth';

/** `TokenOut`. The secret is never in a list response; `prefix` is display only. */
export interface Token {
  id: string;
  kind: TokenKind;
  name: string;
  prefix: string;
  user_id: string;
  client_id: string | null;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  revoked_reason: string | null;
}

/** `TokenCreatedOut`: `token` is shown once and never again. */
export interface TokenCreated extends Token {
  token: string;
}

/** `TokenCreate`; `expires_in_days` 1..365 and ≤ `pat.max_days`. */
export interface TokenCreate {
  name: string;
  expires_in_days?: number;
}

/** `ConnectedAppOut`: one live OAuth grant family. */
export interface ConnectedApp {
  family_id: string;
  client_id: string;
  client_name: string;
  redirect_host: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string;
}

/** `ClientOut`. */
export interface OAuthClient {
  client_id: string;
  client_name: string;
  redirect_uris: string[];
  token_endpoint_auth_method: string;
  registered_at: string;
  revoked_at: string | null;
  active_families: number;
}

/** `CredentialEventOut`: token and client lifecycle (not in `rbac_changes`).
 * `user_id` is null for events about no user (client registration, GC). */
export interface CredentialEvent {
  id: string;
  at: string;
  event: string;
  user_id: string | null;
  actor_user_id: string | null;
  via: string;
  token_id: string | null;
  client_id: string | null;
  details: Record<string, unknown>;
}

/** `ServiceAccountCreate`; `name` 3..60 characters. */
export interface ServiceAccountCreate {
  name: string;
  role: string;
}

/** `ServiceAccountOut`: `UserOut` fields plus the owner. */
export interface ServiceAccount {
  id: string;
  email: string;
  display_name: string;
  kind: string;
  role: string;
  status: string;
  last_seen_at: string | null;
  owner_user_id: string | null;
}

export interface RevokedCount {
  revoked: number;
}

/** `AuthMethodsOut`, plus whether the server answered it (false: read as disabled). */
export interface AuthMethods {
  available: boolean;
  pat: { enabled: boolean; default_days: number; max_days: number };
  /** `hosted_connectors` is true only on an https public URL. */
  oauth: { enabled: boolean; hosted_connectors: boolean };
}

export const AUTH_METHODS_DISABLED: AuthMethods = {
  available: false,
  pat: { enabled: false, default_days: 0, max_days: 0 },
  oauth: { enabled: false, hosted_connectors: false },
};

export async function fetchAuthMethods(): Promise<AuthMethods> {
  try {
    const { data } = await api.get<Omit<AuthMethods, 'available'>>('/meta/auth-methods');
    return { available: true, pat: data.pat, oauth: data.oauth };
  } catch (error) {
    // An older backend without the route: offer neither method (fail closed).
    if (isAxiosError(error) && error.response?.status === 404) return AUTH_METHODS_DISABLED;
    throw error;
  }
}

async function getList<T>(url: string, params?: Record<string, string | number | boolean>) {
  const { data } = await api.get<T[]>(url, { params });
  return data;
}

/** The caller's unrevoked personal tokens, newest first (expired ones included). */
export const listMyTokens = (): Promise<Token[]> => getList<Token>('/me/tokens');

export async function createMyToken(body: TokenCreate): Promise<TokenCreated> {
  const { data } = await api.post<TokenCreated>('/me/tokens', body);
  return data;
}

export async function revokeMyToken(tokenId: string): Promise<void> {
  await api.delete(`/me/tokens/${seg(tokenId)}`);
}

export const listConnectedApps = (): Promise<ConnectedApp[]> =>
  getList<ConnectedApp>('/me/connected-apps');

export async function revokeConnectedApp(familyId: string): Promise<void> {
  await api.delete(`/me/connected-apps/${seg(familyId)}`);
}

export interface AdminTokenFilters {
  user_id?: string;
  kind?: TokenKindFilter;
}

/** Unrevoked tokens in the caller's tenant, newest first, at most 200. */
export const listAdminTokens = (filters: AdminTokenFilters = {}): Promise<Token[]> =>
  getList<Token>('/admin/tokens', compactParams({ ...filters }));

export async function revokeAdminToken(tokenId: string): Promise<void> {
  await api.delete(`/admin/tokens/${seg(tokenId)}`);
}

export async function revokeAllUserTokens(userId: string): Promise<RevokedCount> {
  const { data } = await api.post<RevokedCount>(`/admin/users/${seg(userId)}/tokens/revoke-all`);
  return data;
}

export async function createServiceAccount(body: ServiceAccountCreate): Promise<ServiceAccount> {
  const { data } = await api.post<ServiceAccount>('/admin/service-accounts', body);
  return data;
}

export async function createServiceToken(userId: string, body: TokenCreate) {
  const url = `/admin/service-accounts/${seg(userId)}/tokens`;
  const { data } = await api.post<TokenCreated>(url, body);
  return data;
}

/** OAuth clients are global (dynamic registration knows no tenant). */
export const listClients = (): Promise<OAuthClient[]> => getList<OAuthClient>('/admin/clients');

export async function revokeClient(clientId: string): Promise<void> {
  await api.delete(`/admin/clients/${seg(clientId)}`);
}

/** `GET /admin/credential-events`: newest first, no cursor, only a size. */
export interface CredentialEventFilters {
  user_id?: string;
  /** 1..500; the backend defaults to 100. */
  limit?: number;
}

export const listCredentialEvents = (
  filters: CredentialEventFilters = {},
): Promise<CredentialEvent[]> =>
  getList<CredentialEvent>('/admin/credential-events', compactParams({ ...filters }));
