import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../query-keys';
import {
  createMyToken,
  createServiceAccount,
  createServiceToken,
  listAdminTokens,
  listClients,
  listConnectedApps,
  listMyTokens,
  revokeAdminToken,
  revokeAllUserTokens,
  revokeClient,
  revokeConnectedApp,
  revokeMyToken,
  type AdminTokenFilters,
  type ServiceAccountCreate,
  type TokenCreate,
} from '../tokens';
import { useAccessMutation } from './use-access-mutation';

// MCP credentials (phase 4). Token and client writes are identity writes, not
// AccessAdmin writes, so their 409s (e.g. the token limit) offer no Retry. Responses carrying a secret use gcTime 0 so the
// token never lingers in the mutation cache after the reveal unmounts.

const SECRET = { gcTime: 0 };
const ADMIN_CREDENTIAL_VIEWS = [queryKeys.adminTokens, queryKeys.clients, queryKeys.audit];

export function useMyTokens(enabled = true) {
  return useQuery({ queryKey: queryKeys.myTokens, queryFn: listMyTokens, enabled });
}

export function useCreateMyToken() {
  return useAccessMutation({
    mutationFn: (body: TokenCreate) => createMyToken(body),
    invalidates: [queryKeys.myTokens],
    ...SECRET,
  });
}

export function useRevokeMyToken() {
  return useAccessMutation({
    mutationFn: (tokenId: string) => revokeMyToken(tokenId),
    invalidates: [queryKeys.myTokens],
  });
}

export function useConnectedApps(enabled = true) {
  return useQuery({ queryKey: queryKeys.connectedApps, queryFn: listConnectedApps, enabled });
}

export function useRevokeConnectedApp() {
  return useAccessMutation({
    mutationFn: (familyId: string) => revokeConnectedApp(familyId),
    invalidates: [queryKeys.connectedApps],
  });
}

export function useAdminTokens(filters: AdminTokenFilters = {}, enabled = true) {
  return useQuery({
    queryKey: queryKeys.adminTokenList(filters),
    queryFn: () => listAdminTokens(filters),
    enabled,
  });
}

export function useRevokeAdminToken() {
  return useAccessMutation({
    mutationFn: (tokenId: string) => revokeAdminToken(tokenId),
    invalidates: ADMIN_CREDENTIAL_VIEWS,
  });
}

export function useRevokeAllUserTokens() {
  return useAccessMutation({
    mutationFn: (userId: string) => revokeAllUserTokens(userId),
    invalidates: ADMIN_CREDENTIAL_VIEWS,
  });
}

/** Runs through AccessAdmin (phase 4 `create_service_account`): Retry on a stale-actor 409. */
export function useCreateServiceAccount() {
  return useAccessMutation({
    mutationFn: (body: ServiceAccountCreate) => createServiceAccount(body),
    invalidates: [queryKeys.users, queryKeys.audit],
    retryOn409: true,
  });
}

export interface ServiceTokenVars {
  userId: string;
  body: TokenCreate;
}

export function useCreateServiceToken() {
  return useAccessMutation({
    mutationFn: ({ userId, body }: ServiceTokenVars) => createServiceToken(userId, body),
    invalidates: ADMIN_CREDENTIAL_VIEWS,
    ...SECRET,
  });
}

export function useClients(enabled = true) {
  return useQuery({ queryKey: queryKeys.clients, queryFn: listClients, enabled });
}

export function useRevokeClient() {
  return useAccessMutation({
    mutationFn: (clientId: string) => revokeClient(clientId),
    invalidates: ADMIN_CREDENTIAL_VIEWS,
  });
}
