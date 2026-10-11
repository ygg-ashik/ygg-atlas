import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { queryKeys } from '../query-keys';
import { httpError } from '../test-support';
import { createQueryWrapper } from './test-query-wrapper';
import {
  useApproveRequest,
  useCreateRequest,
  useDeclineRequest,
  useRequestQueue,
} from './use-access-requests';

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../axios-instance', () => ({ api: http }));

const row = (id: string) => ({ id, kind: 'group', status: 'pending' });

describe('useRequestQueue', () => {
  beforeEach(() => {
    http.get.mockReset();
  });

  it('follows next_cursor and merges pages', async () => {
    http.get
      .mockResolvedValueOnce({ data: { items: [row('r1'), row('r2')], next_cursor: 'c1' } })
      .mockResolvedValueOnce({ data: { items: [row('r3')], next_cursor: null } });
    const { result } = renderHook(() => useRequestQueue('pending'), {
      wrapper: createQueryWrapper().wrapper,
    });
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(result.current.hasNextPage).toBe(true);
    expect(http.get).toHaveBeenLastCalledWith('/admin/requests', {
      params: { status: 'pending', limit: 50 },
    });

    await act(() => result.current.fetchNextPage());
    await waitFor(() => expect(result.current.items).toHaveLength(3));
    expect(http.get).toHaveBeenLastCalledWith('/admin/requests', {
      params: { status: 'pending', cursor: 'c1', limit: 50 },
    });
    expect(result.current.items.map((r) => r.id)).toEqual(['r1', 'r2', 'r3']);
    expect(result.current.hasNextPage).toBe(false);
  });

  it("narrows to one requester's requests under its own cache key", async () => {
    http.get.mockResolvedValue({ data: { items: [row('r9')], next_cursor: null } });
    const { client, wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useRequestQueue('all', { userId: 'u-omar' }), { wrapper });
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    expect(http.get).toHaveBeenLastCalledWith('/admin/requests', {
      params: { status: 'all', user_id: 'u-omar', limit: 50 },
    });
    expect(client.getQueryData(queryKeys.requestQueueList('all', 'u-omar'))).toBeDefined();
  });

  it('stays idle while disabled', () => {
    renderHook(() => useRequestQueue('decided', { enabled: false }), {
      wrapper: createQueryWrapper().wrapper,
    });
    expect(http.get).not.toHaveBeenCalled();
  });
});

describe('request mutations', () => {
  beforeEach(() => {
    http.post.mockReset();
  });

  it('approve refreshes every access view on success', async () => {
    http.post.mockResolvedValue({ data: { id: 'r1', status: 'approved' } });
    const { client, wrapper } = createQueryWrapper();
    const spy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useApproveRequest(), { wrapper });
    await act(() => result.current.mutateAsync({ requestId: 'r1', decision: { note: 'ok' } }));
    expect(http.post).toHaveBeenCalledWith('/admin/requests/r1/approve', { note: 'ok' });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.admin });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.myAccess });
  });

  it('approve: a stale-actor 409 refetches /me/access and offers Retry', async () => {
    http.post.mockRejectedValue(
      httpError(409, { detail: 'Access changed while this request was running; retry.' }),
    );
    const { client, wrapper } = createQueryWrapper();
    const spy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useApproveRequest(), { wrapper });
    act(() => result.current.mutate({ requestId: 'r1' }));
    await waitFor(() => expect(result.current.errorInfo).not.toBeNull());
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.myAccess });
    expect(result.current.errorInfo).toMatchObject({
      kind: 'conflict',
      message: 'Access changed while this request was running; retry.',
      retry: { actionLabel: 'Retry' },
    });
  });

  it('a 403 carries the backend sentence and invalidates nothing', async () => {
    http.post.mockRejectedValue(httpError(403, { detail: "You can't grant above your role." }));
    const { client, wrapper } = createQueryWrapper();
    const spy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useDeclineRequest(), { wrapper });
    act(() => result.current.mutate({ requestId: 'r1' }));
    await waitFor(() => expect(result.current.errorInfo?.kind).toBe('forbidden'));
    expect(result.current.errorInfo?.message).toBe("You can't grant above your role.");
    expect(spy).not.toHaveBeenCalled();
  });

  it('creating a request refreshes only own requests and the badge count', async () => {
    http.post.mockResolvedValue({ data: { id: 'r9' } });
    const { client, wrapper } = createQueryWrapper();
    const spy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useCreateRequest(), { wrapper });
    await act(() =>
      result.current.mutateAsync({ kind: 'role', target: 'builder', note: 'Need dashboards' }),
    );
    expect(spy.mock.calls.map(([f]) => f?.queryKey)).toEqual([
      queryKeys.myRequests,
      queryKeys.myAccess,
      queryKeys.users,
    ]);
  });

  it('create: a duplicate 409 refetches /me/access but offers no Retry', async () => {
    http.post.mockRejectedValue(
      httpError(409, { detail: "You already asked for this; it's pending." }),
    );
    const { client, wrapper } = createQueryWrapper();
    const spy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useCreateRequest(), { wrapper });
    act(() => result.current.mutate({ kind: 'group', target: 'g1', note: 'n' }));
    await waitFor(() => expect(result.current.errorInfo).not.toBeNull());
    expect(result.current.errorInfo).toMatchObject({
      kind: 'conflict',
      message: "You already asked for this; it's pending.",
      retry: null,
    });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.myAccess });
  });

  it('decline refreshes the queue, user views (pending_requests) and the badge', async () => {
    http.post.mockResolvedValue({ data: { id: 'r1', status: 'declined' } });
    const { client, wrapper } = createQueryWrapper();
    const spy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useDeclineRequest(), { wrapper });
    await act(() => result.current.mutateAsync({ requestId: 'r1', decision: { note: 'no' } }));
    expect(http.post).toHaveBeenCalledWith('/admin/requests/r1/decline', { note: 'no' });
    expect(spy.mock.calls.map(([f]) => f?.queryKey)).toEqual([
      queryKeys.requestQueue,
      queryKeys.users,
      queryKeys.myAccess,
    ]);
  });
});
