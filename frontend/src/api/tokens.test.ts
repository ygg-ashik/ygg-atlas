import { beforeEach, describe, expect, it, vi } from 'vitest';
import { answerWith, http } from './test-api-mock';
import { httpError } from './test-support';
import {
  AUTH_METHODS_DISABLED,
  createMyToken,
  createServiceAccount,
  createServiceToken,
  fetchAuthMethods,
  listAdminTokens,
  listClients,
  listConnectedApps,
  listCredentialEvents,
  listMyTokens,
  revokeAdminToken,
  revokeAllUserTokens,
  revokeClient,
  revokeConnectedApp,
  revokeMyToken,
  type CredentialEvent,
  type Token,
} from './tokens';

vi.mock('./axios-instance', async () => (await import('./test-api-mock')).apiMock);

// Exactly the fields of the backend schemas (app/mcp/schemas.py).
const TOKEN: Token = {
  id: 't1',
  kind: 'oauth_refresh',
  name: 'Claude Code',
  prefix: 'atl_ort_77c1ab',
  user_id: 'u1',
  client_id: 'oc_8f3a1c',
  created_at: '2026-10-01T00:00:00Z',
  expires_at: '2026-12-30T00:00:00Z',
  last_used_at: null,
  revoked_at: null,
  revoked_reason: null,
};
const EVENT: CredentialEvent = {
  id: 'e1',
  at: '2026-10-09T08:00:00Z',
  event: 'client.registered',
  user_id: null,
  actor_user_id: null,
  via: 'system',
  token_id: null,
  client_id: 'oc_8f3a1c',
  details: {},
};

describe('tokens client', () => {
  beforeEach(() => answerWith([]));

  it('maps the self-service routes', async () => {
    await expect(listMyTokens()).resolves.toEqual([]);
    expect(http.get).toHaveBeenCalledWith('/me/tokens', { params: undefined });
    await createMyToken({ name: 'laptop', expires_in_days: 30 });
    expect(http.post).toHaveBeenCalledWith('/me/tokens', { name: 'laptop', expires_in_days: 30 });
    await revokeMyToken('t1');
    expect(http.delete).toHaveBeenCalledWith('/me/tokens/t1');
    await listConnectedApps();
    expect(http.get).toHaveBeenCalledWith('/me/connected-apps', { params: undefined });
    await revokeConnectedApp('f1');
    expect(http.delete).toHaveBeenCalledWith('/me/connected-apps/f1');
  });

  it('maps the admin routes', async () => {
    await listAdminTokens({ kind: 'service' });
    expect(http.get).toHaveBeenCalledWith('/admin/tokens', { params: { kind: 'service' } });
    await revokeAdminToken('t1');
    expect(http.delete).toHaveBeenCalledWith('/admin/tokens/t1');
    await revokeAllUserTokens('u1');
    expect(http.post).toHaveBeenCalledWith('/admin/users/u1/tokens/revoke-all');
    await createServiceAccount({ name: 'etl-bot', role: 'viewer' });
    expect(http.post).toHaveBeenCalledWith('/admin/service-accounts', {
      name: 'etl-bot',
      role: 'viewer',
    });
    await createServiceToken('s1', { name: 'nightly' });
    expect(http.post).toHaveBeenCalledWith('/admin/service-accounts/s1/tokens', {
      name: 'nightly',
    });
    await listClients();
    expect(http.get).toHaveBeenCalledWith('/admin/clients', { params: undefined });
    await revokeClient('client:a');
    expect(http.delete).toHaveBeenCalledWith('/admin/clients/client%3Aa');
    await listCredentialEvents({ user_id: 'u1', limit: 100 });
    expect(http.get).toHaveBeenCalledWith('/admin/credential-events', {
      params: { user_id: 'u1', limit: 100 },
    });
  });

  it('list reads return the backend arrays; every failure is an error', async () => {
    http.get.mockResolvedValueOnce({ data: [TOKEN] });
    await expect(listAdminTokens()).resolves.toEqual([TOKEN]);
    http.get.mockResolvedValueOnce({ data: [EVENT] });
    await expect(listCredentialEvents({ limit: 100 })).resolves.toEqual([EVENT]);
    http.get.mockRejectedValue(httpError(404, { detail: 'Not Found' }));
    await expect(listMyTokens()).rejects.toMatchObject({ response: { status: 404 } });
    await expect(listCredentialEvents()).rejects.toMatchObject({ response: { status: 404 } });
    http.get.mockRejectedValue(httpError(403, { detail: 'no' }));
    await expect(listClients()).rejects.toMatchObject({ response: { status: 403 } });
  });

  it('reads auth methods; 404 means both disabled', async () => {
    const methods = {
      pat: { enabled: true, default_days: 90, max_days: 365 },
      oauth: { enabled: true, hosted_connectors: false },
    };
    http.get.mockResolvedValue({ data: methods });
    await expect(fetchAuthMethods()).resolves.toEqual({ available: true, ...methods });
    expect(http.get).toHaveBeenCalledWith('/meta/auth-methods');
    http.get.mockRejectedValue(httpError(404, { detail: 'Not Found' }));
    await expect(fetchAuthMethods()).resolves.toEqual(AUTH_METHODS_DISABLED);
    http.get.mockRejectedValue(httpError(500));
    await expect(fetchAuthMethods()).rejects.toBeTruthy();
  });
});
