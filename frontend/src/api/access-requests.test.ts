import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  approveRequest,
  cancelRequest,
  createRequest,
  declineRequest,
  fetchRequestOptions,
  listDecidableRequests,
  listMyRequests,
} from './access-requests';
import { answerWith, http } from './test-api-mock';

vi.mock('./axios-instance', async () => (await import('./test-api-mock')).apiMock);

describe('access requests client', () => {
  beforeEach(() => answerWith({ id: 'r1', status: 'pending' }));

  it('maps the self-service routes', async () => {
    await listMyRequests();
    expect(http.get).toHaveBeenCalledWith('/me/requests');
    await fetchRequestOptions('demo/order/revenue');
    expect(http.get).toHaveBeenCalledWith('/me/requests/options', {
      params: { resource: 'demo/order/revenue' },
    });
    const body = { kind: 'resource' as const, target: 'demo/order/revenue', note: 'Q3 review' };
    await expect(createRequest(body)).resolves.toEqual({ id: 'r1', status: 'pending' });
    expect(http.post).toHaveBeenCalledWith('/me/requests', body);
    await cancelRequest('r1');
    expect(http.post).toHaveBeenCalledWith('/me/requests/r1/cancel');
  });

  it('pages the decision queue with status, cursor and limit', async () => {
    await listDecidableRequests({ status: 'all', cursor: 'c2', limit: 50 });
    expect(http.get).toHaveBeenCalledWith('/admin/requests', {
      params: { status: 'all', cursor: 'c2', limit: 50 },
    });
    await listDecidableRequests();
    expect(http.get).toHaveBeenLastCalledWith('/admin/requests', { params: {} });
    await listDecidableRequests({ status: 'decided', user_id: 'u-omar' });
    expect(http.get).toHaveBeenLastCalledWith('/admin/requests', {
      params: { status: 'decided', user_id: 'u-omar' },
    });
  });

  it('keeps absent vs null expiry distinct on approve', async () => {
    await approveRequest('r1');
    expect(http.post).toHaveBeenLastCalledWith('/admin/requests/r1/approve', {});
    await approveRequest('r1', { note: 'ok', expires_at: null });
    expect(JSON.parse(JSON.stringify(http.post.mock.lastCall?.[1]))).toEqual({
      note: 'ok',
      expires_at: null,
    });
    await declineRequest('r1', { note: 'Use the finance group' });
    expect(http.post).toHaveBeenLastCalledWith('/admin/requests/r1/decline', {
      note: 'Use the finance group',
    });
  });
});
