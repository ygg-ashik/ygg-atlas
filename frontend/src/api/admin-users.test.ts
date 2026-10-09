import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchEffectiveAccess, fetchUserDetail, listUsers, updateUser } from './admin-users';
import { answerWith, http } from './test-api-mock';

vi.mock('./axios-instance', async () => (await import('./test-api-mock')).apiMock);

describe('admin users client', () => {
  beforeEach(() => answerWith({ items: [], next_cursor: null }));

  it('sends only the filters that are set, with cursor and limit', async () => {
    const page = await listUsers({
      filters: { q: 'sara', role: '', status: 'disabled', kind: undefined },
      cursor: 'c1',
      limit: 50,
    });
    expect(page).toEqual({ items: [], next_cursor: null });
    expect(http.get).toHaveBeenCalledWith('/admin/users', {
      params: { q: 'sara', status: 'disabled', cursor: 'c1', limit: 50 },
    });
  });

  it('lists with no params by default', async () => {
    await listUsers();
    expect(http.get).toHaveBeenCalledWith('/admin/users', { params: {} });
  });

  it('reads detail and patches role/status', async () => {
    await fetchUserDetail('u1');
    expect(http.get).toHaveBeenCalledWith('/admin/users/u1');
    await updateUser('u1', { role: 'builder' });
    expect(http.patch).toHaveBeenCalledWith('/admin/users/u1', { role: 'builder' });
  });

  it('probes effective access with an optional resource', async () => {
    await fetchEffectiveAccess('u1', 'demo/order/revenue');
    expect(http.get).toHaveBeenCalledWith('/admin/users/u1/access', {
      params: { resource: 'demo/order/revenue' },
    });
    await fetchEffectiveAccess('u1');
    expect(http.get).toHaveBeenLastCalledWith('/admin/users/u1/access', { params: {} });
  });
});
