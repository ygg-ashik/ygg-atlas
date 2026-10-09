import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  createGrant,
  createGroup,
  deleteGroup,
  fetchGroupDetail,
  listGrants,
  listGroups,
  listMembers,
  putMember,
  removeMember,
  revokeGrant,
  updateGroup,
} from './admin-groups';
import { answerWith, http } from './test-api-mock';

vi.mock('./axios-instance', async () => (await import('./test-api-mock')).apiMock);

describe('admin groups client', () => {
  beforeEach(() => answerWith([]));

  it('maps group routes', async () => {
    await listGroups();
    expect(http.get).toHaveBeenCalledWith('/admin/groups');
    await fetchGroupDetail('g1');
    expect(http.get).toHaveBeenCalledWith('/admin/groups/g1');
    await createGroup({ name: 'Finance', parent_id: null });
    expect(http.post).toHaveBeenCalledWith('/admin/groups', { name: 'Finance', parent_id: null });
    await updateGroup('g1', { parent_id: null });
    expect(http.patch).toHaveBeenCalledWith('/admin/groups/g1', { parent_id: null });
    await deleteGroup('g1');
    expect(http.delete).toHaveBeenCalledWith('/admin/groups/g1');
  });

  it('maps member routes with the standing body', async () => {
    await listMembers('g1');
    expect(http.get).toHaveBeenCalledWith('/admin/groups/g1/members');
    await putMember('g1', 'u1');
    expect(http.put).toHaveBeenCalledWith('/admin/groups/g1/members/u1', { standing: 'member' });
    await putMember('g1', 'u1', 'manager');
    expect(http.put).toHaveBeenLastCalledWith('/admin/groups/g1/members/u1', {
      standing: 'manager',
    });
    await removeMember('g1', 'u1');
    expect(http.delete).toHaveBeenCalledWith('/admin/groups/g1/members/u1');
  });

  it('maps grant routes', async () => {
    await listGrants('group', 'g1');
    expect(http.get).toHaveBeenCalledWith('/admin/grants', {
      params: { subject_type: 'group', subject_id: 'g1' },
    });
    const body = {
      subject_type: 'user' as const,
      subject_id: 'u1',
      effect: 'allow' as const,
      target_kind: 'resource' as const,
      target: 'demo/*',
      reason: 'Quarter close',
      expires_at: null,
    };
    await createGrant(body);
    expect(http.post).toHaveBeenCalledWith('/admin/grants', body);
    await revokeGrant('gr1');
    expect(http.delete).toHaveBeenCalledWith('/admin/grants/gr1');
  });
});
