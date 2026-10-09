// Admin reads and writes: each hook calls its route and refreshes the right views.
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { queryKeys } from '../query-keys';
import { createQueryWrapper } from './test-query-wrapper';
import { useCapabilityCatalog } from './use-capability-catalog';
import { useCatalogResources } from './use-catalog-resources';
import { useAdminUsers, useEffectiveAccess, useUpdateUser, useUserDetail } from './use-admin-users';
import {
  useCreateGroup,
  useDeleteGroup,
  useGroupDetail,
  useGroupMembers,
  useGroups,
  useMemberCandidates,
  usePutMember,
  useRemoveMember,
  useUpdateGroup,
} from './use-admin-groups';
import { useCreateGrant, useGrants, useRevokeGrant } from './use-admin-grants';
import { useAuditSummary, useChanges, useDecisions } from './use-audit';
import { useCancelRequest, useMyRequests, useRequestOptions } from './use-access-requests';

const http = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));
vi.mock('../axios-instance', () => ({ api: http }));

beforeEach(() => {
  for (const fn of Object.values(http)) {
    fn.mockReset();
    fn.mockResolvedValue({ data: { items: [], next_cursor: null } });
  }
});

async function settle<T>(useHook: () => { isSuccess: boolean } & T) {
  const { result } = renderHook(useHook, { wrapper: createQueryWrapper().wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  return result;
}

describe('useMemberCandidates', () => {
  it('stays idle below 3 characters and above 100, then searches trimmed', async () => {
    const { wrapper } = createQueryWrapper();
    renderHook(() => useMemberCandidates('g1', ' sa '), { wrapper });
    renderHook(() => useMemberCandidates('g1', 'x'.repeat(101)), { wrapper });
    expect(http.get).not.toHaveBeenCalled();
    http.get.mockResolvedValue({ data: [] });
    await settle(() => useMemberCandidates('g1', ' sar '));
    expect(http.get).toHaveBeenLastCalledWith('/admin/groups/g1/member-candidates', {
      params: { q: 'sar' },
    });
  });
});

describe('admin reads', () => {
  it('call their routes', async () => {
    await settle(() => useAdminUsers({ role: 'viewer' }));
    expect(http.get).toHaveBeenLastCalledWith('/admin/users', {
      params: { role: 'viewer', limit: 50 },
    });
    await settle(() => useUserDetail('u1'));
    expect(http.get).toHaveBeenLastCalledWith('/admin/users/u1');
    await settle(() => useEffectiveAccess('u1', 'demo/order/revenue'));
    expect(http.get).toHaveBeenLastCalledWith('/admin/users/u1/access', {
      params: { resource: 'demo/order/revenue' },
    });
    await settle(() => useGroups());
    await settle(() => useGroupDetail('g1'));
    await settle(() => useGroupMembers('g1'));
    expect(http.get).toHaveBeenLastCalledWith('/admin/groups/g1/members');
    await settle(() => useGrants({ subjectType: 'user', subjectId: 'u1' }));
    expect(http.get).toHaveBeenLastCalledWith('/admin/grants', {
      params: { subject_type: 'user', subject_id: 'u1' },
    });
    await settle(() => useChanges({ action: 'grant.create' }));
    expect(http.get).toHaveBeenLastCalledWith('/admin/rbac-changes', {
      params: { action: 'grant.create', limit: 100 },
    });
    await settle(() => useDecisions({ decision: 'deny' }));
    await settle(() => useAuditSummary(7));
    expect(http.get).toHaveBeenLastCalledWith('/admin/audit/summary', { params: { days: 7 } });
    await settle(() => useCatalogResources('u1'));
    await settle(() => useCapabilityCatalog());
    await settle(() => useMyRequests());
    await settle(() => useRequestOptions('demo/order/revenue'));
  });

  it('stay idle without an id', () => {
    const { wrapper } = createQueryWrapper();
    renderHook(() => useUserDetail(null), { wrapper });
    renderHook(() => useGroupDetail(null), { wrapper });
    renderHook(() => useGrants(null), { wrapper });
    renderHook(() => useRequestOptions(null), { wrapper });
    expect(http.get).not.toHaveBeenCalled();
  });
});

type Write = () => { mutateAsync: (vars: never) => Promise<unknown> };

describe('admin writes refresh every access view', () => {
  it.each<[string, Write, unknown]>([
    ['update user', () => useUpdateUser(), { userId: 'u1', update: { status: 'disabled' } }],
    ['create group', () => useCreateGroup(), { name: 'Ops' }],
    ['update group', () => useUpdateGroup(), { groupId: 'g1', update: { name: 'Ops' } }],
    ['delete group', () => useDeleteGroup(), 'g1'],
    ['put member', () => usePutMember(), { groupId: 'g1', userId: 'u1' }],
    ['remove member', () => useRemoveMember(), { groupId: 'g1', userId: 'u1' }],
    [
      'create grant',
      () => useCreateGrant(),
      { subject_type: 'group', subject_id: 'g1', target: 'demo/*' },
    ],
    ['revoke grant', () => useRevokeGrant(), 'gr1'],
  ])('%s', async (_name, useWrite, vars) => {
    const { client, wrapper } = createQueryWrapper();
    const spy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(useWrite, { wrapper });
    await act(() => (result.current.mutateAsync as (v: unknown) => Promise<unknown>)(vars));
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.admin });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.myAccess });
  });

  it('cancel calls the cancel route', async () => {
    const { result } = renderHook(() => useCancelRequest(), {
      wrapper: createQueryWrapper().wrapper,
    });
    await act(() => result.current.mutateAsync('r1'));
    expect(http.post).toHaveBeenCalledWith('/me/requests/r1/cancel');
  });
});
