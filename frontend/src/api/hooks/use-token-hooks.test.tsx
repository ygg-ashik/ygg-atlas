// Phase-4 writes: routes, invalidation, and secrets kept out of the cache.
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { queryKeys } from '../query-keys';
import { httpError } from '../test-support';
import { createQueryWrapper } from './test-query-wrapper';
import {
  useCreateMyToken,
  useCreateServiceAccount,
  useCreateServiceToken,
  useRevokeAdminToken,
  useRevokeAllUserTokens,
  useRevokeClient,
  useRevokeConnectedApp,
  useRevokeMyToken,
} from './use-tokens';
import { useDeleteUserAttribute, usePutLabelClass, usePutUserAttribute } from './use-row-field';

const http = vi.hoisted(() => ({ post: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock('../axios-instance', () => ({ api: http }));

beforeEach(() => {
  for (const fn of Object.values(http)) {
    fn.mockReset();
    fn.mockResolvedValue({ data: { token: 'atl_pat_secret', revoked: 2 } });
  }
});

async function run<V>(useWrite: () => { mutateAsync: (v: V) => Promise<unknown> }, vars: V) {
  const { client, wrapper } = createQueryWrapper();
  const spy = vi.spyOn(client, 'invalidateQueries');
  const { result, unmount } = renderHook(useWrite, { wrapper });
  await act(() => result.current.mutateAsync(vars));
  return { client, unmount, keys: spy.mock.calls.map(([f]) => f?.queryKey) };
}

describe('token writes', () => {
  it('mint a personal token; the secret leaves the cache once the reveal unmounts', async () => {
    const { client, unmount, keys } = await run(() => useCreateMyToken(), { name: 'laptop' });
    expect(http.post).toHaveBeenCalledWith('/me/tokens', { name: 'laptop' });
    expect(keys).toEqual([queryKeys.myTokens]);
    unmount();
    await vi.waitFor(() => expect(client.getMutationCache().getAll()).toHaveLength(0));
  });

  it('revoke own tokens and connected apps', async () => {
    expect((await run(() => useRevokeMyToken(), 't1')).keys).toEqual([queryKeys.myTokens]);
    expect((await run(() => useRevokeConnectedApp(), 'f1')).keys).toEqual([
      queryKeys.connectedApps,
    ]);
    expect(http.delete).toHaveBeenCalledWith('/me/connected-apps/f1');
  });

  it('admin credential writes refresh tokens, clients and audit', async () => {
    const expected = [queryKeys.adminTokens, queryKeys.clients, queryKeys.audit];
    expect((await run(() => useRevokeAdminToken(), 't1')).keys).toEqual(expected);
    expect((await run(() => useRevokeAllUserTokens(), 'u1')).keys).toEqual(expected);
    expect((await run(() => useRevokeClient(), 'c1')).keys).toEqual(expected);
    const minted = await run(() => useCreateServiceToken(), { userId: 's1', body: { name: 'n' } });
    expect(minted.keys).toEqual(expected);
    expect(http.post).toHaveBeenCalledWith('/admin/service-accounts/s1/tokens', { name: 'n' });
    const created = await run(() => useCreateServiceAccount(), { name: 'etl', role: 'viewer' });
    expect(created.keys).toEqual([queryKeys.users, queryKeys.audit]);
  });
});

describe('409 Retry is opt-in', () => {
  it('a token write 409 (identity, not AccessAdmin) offers no Retry', async () => {
    http.post.mockRejectedValue(
      httpError(409, { detail: 'You have the maximum number of tokens.' }),
    );
    const { result } = renderHook(() => useCreateMyToken(), {
      wrapper: createQueryWrapper().wrapper,
    });
    act(() => result.current.mutate({ name: 'x' }));
    await waitFor(() => expect(result.current.errorInfo?.kind).toBe('conflict'));
    expect(result.current.errorInfo?.retry).toBeNull();
  });

  it('an AccessAdmin write 409 (row and field) offers Retry', async () => {
    http.put.mockRejectedValue(
      httpError(409, { detail: 'Access changed while this request was running; retry.' }),
    );
    const { result } = renderHook(() => usePutUserAttribute(), {
      wrapper: createQueryWrapper().wrapper,
    });
    act(() => result.current.mutate({ userId: 'u1', key: 'csm', value: 'x' }));
    await waitFor(() => expect(result.current.errorInfo?.kind).toBe('conflict'));
    expect(result.current.errorInfo?.retry).toEqual({ actionLabel: 'Retry' });
  });
});

describe('row and field writes (phase 3)', () => {
  it('refresh every access view', async () => {
    const all = [queryKeys.admin, queryKeys.myAccess];
    expect(
      (await run(() => usePutUserAttribute(), { userId: 'u1', key: 'csm', value: 'x' })).keys,
    ).toEqual(all);
    expect(http.put).toHaveBeenCalledWith('/admin/users/u1/attributes/csm', { value: 'x' });
    expect((await run(() => useDeleteUserAttribute(), { userId: 'u1', key: 'csm' })).keys).toEqual(
      all,
    );
    const label = await run(() => usePutLabelClass(), {
      labelClass: 'person_name',
      body: { mode: 'suppress' as const },
    });
    expect(label.keys).toEqual(all);
  });
});
