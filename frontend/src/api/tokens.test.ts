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
} from './tokens';

vi.mock('./axios-instance', async () => (await import('./test-api-mock')).apiMock);

describe('tokens client (phase 4)', () => {
  beforeEach(() => answerWith([]));

  it('maps the self-service routes', async () => {
    await expect(listMyTokens()).resolves.toEqual({ available: true, data: [] });
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

  it('resolves list reads to unavailable when the route is missing and rethrows others', async () => {
    http.get.mockRejectedValue(httpError(404, { detail: 'Not Found' }));
    const missing = { available: false, reason: 'missing' };
    await expect(listMyTokens()).resolves.toEqual(missing);
    await expect(listCredentialEvents()).resolves.toEqual(missing);
    http.get.mockRejectedValue(httpError(404, { detail: 'No such user.' }));
    await expect(listAdminTokens({ user_id: 'u9' })).rejects.toBeTruthy();
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
