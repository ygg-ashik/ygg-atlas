import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type MeAccess } from '../access';
import { queryKeys } from '../query-keys';
import { httpError } from '../test-support';
import { createQueryWrapper } from './test-query-wrapper';
import { useMyAccess } from './use-my-access';

const fetchMyAccess = vi.hoisted(() => vi.fn());
vi.mock('../access', () => ({ fetchMyAccess }));

const ADMIN: MeAccess = {
  role: 'admin',
  capabilities: ['admin:users', 'admin:groups', 'chat:use'],
  groups: [{ id: 'g1', name: 'Finance', standing: 'manager' }],
  has_data_access: false,
  user_id: 'u1',
  email: 'sara@yougotagift.com',
  display_name: 'Sara',
  pending_requests: 1,
  pending_approvals: 3,
  is_manager: true,
};

describe('useMyAccess', () => {
  beforeEach(() => {
    fetchMyAccess.mockReset();
  });

  it('holds no capabilities while loading', () => {
    fetchMyAccess.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useMyAccess(), { wrapper: createQueryWrapper().wrapper });
    expect(result.current.status).toBe('loading');
    expect(result.current.capabilities).toEqual([]);
    expect(result.current.can('admin:users')).toBe(false);
  });

  it('exposes capabilities, manager standing and counts when ready', async () => {
    fetchMyAccess.mockResolvedValue(ADMIN);
    const { result } = renderHook(() => useMyAccess(), { wrapper: createQueryWrapper().wrapper });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.access).toEqual(ADMIN);
    expect(result.current.can('admin:users')).toBe(true);
    expect(result.current.can('admin:audit')).toBe(false);
    expect(result.current.canAny('admin:audit', 'admin:groups')).toBe(true);
    expect(result.current).toMatchObject({
      isManager: true,
      pendingRequests: 1,
      pendingApprovals: 3,
    });
  });

  it('fails closed on error: no capabilities, status unavailable', async () => {
    fetchMyAccess.mockRejectedValue(httpError(503, { detail: 'unavailable' }));
    const { result } = renderHook(() => useMyAccess(), { wrapper: createQueryWrapper().wrapper });
    await waitFor(() => expect(result.current.status).toBe('unavailable'));
    expect(result.current).toMatchObject({
      access: null,
      capabilities: [],
      isManager: false,
      pendingRequests: 0,
      pendingApprovals: 0,
    });
    expect(result.current.canAny('admin:users', 'admin:groups')).toBe(false);
  });

  it('drops stale access when a refetch fails', async () => {
    fetchMyAccess.mockResolvedValueOnce(ADMIN);
    const { client, wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useMyAccess(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    fetchMyAccess.mockRejectedValue(httpError(500));
    await client.refetchQueries({ queryKey: queryKeys.myAccess });
    await waitFor(() => expect(result.current.status).toBe('unavailable'));
    expect(result.current.can('admin:users')).toBe(false);
  });
});
