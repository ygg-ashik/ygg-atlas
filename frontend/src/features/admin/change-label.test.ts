import { describe, expect, it } from 'vitest';
import { type Change } from '@/api/audit';
import { changeLabel, nameBook, shortId } from './change-label';

const G = '6f1c2a90-1111-4222-8333-944455556666';
const U = '3b7e0d12-aaaa-4bbb-8ccc-dddeeefff000';
const R = '7b51c0de-0000-4000-8000-000000000001';

function change(overrides: Partial<Change>): Change {
  return {
    id: 'c1',
    actor_user_id: null,
    via: 'api',
    action: 'user.role',
    object_type: 'user',
    object_id: U,
    before: null,
    after: null,
    at: '2026-10-09T09:41:00Z',
    actor: null,
    ...overrides,
  };
}

const book = nameBook({
  groups: [{ id: G, name: 'marketing' }],
  users: [{ user_id: U, email: 'nour.alamin@yougotagift.com' }],
});

describe('shortId', () => {
  it('keeps the first uuid segment', () => {
    expect(shortId(G)).toBe('6f1c2a90…');
    expect(shortId('u-1')).toBe('u-1');
  });
});

describe('changeLabel', () => {
  it('names a membership as user → group, and ← on removal', () => {
    const put = change({
      action: 'member.put',
      object_type: 'group_member',
      object_id: `${G}:${U}`,
      after: { group_id: G, user_id: U, standing: 'member' },
    });
    expect(changeLabel(put, book)).toBe('nour.alamin@ → marketing');
    const removed = change({
      action: 'member.remove',
      object_type: 'group_member',
      object_id: `${G}:${U}`,
      before: { group_id: G, user_id: U, standing: 'member' },
    });
    expect(changeLabel(removed, book)).toBe('nour.alamin@ ← marketing');
  });

  it('falls back to short ids from the compound key when names are unknown', () => {
    const put = change({ object_type: 'group_member', object_id: `${G}:${U}`, after: null });
    expect(changeLabel(put)).toBe('user 3b7e0d12… → group 6f1c2a90…');
  });

  it('names a group by its snapshot name, then the book', () => {
    const created = change({
      action: 'group.create',
      object_type: 'group',
      object_id: G,
      after: { id: G, name: 'marketing-paid' },
    });
    expect(changeLabel(created)).toBe('marketing-paid');
    expect(changeLabel(change({ object_type: 'group', object_id: G }), book)).toBe('marketing');
  });

  it('names a grant by its subject and target pattern', () => {
    const grant = change({
      action: 'grant.create',
      object_type: 'grant',
      object_id: 'g-1',
      after: { subject_type: 'group', subject_id: G, effect: 'allow', target: 'demo/checkout/*' },
    });
    expect(changeLabel(grant, book)).toBe('group:marketing · demo/checkout/*');
    const revoked = change({
      action: 'grant.revoke',
      object_type: 'grant',
      object_id: 'g-2',
      before: { subject_type: 'user', subject_id: U, target: 'deepsales/*' },
    });
    expect(changeLabel(revoked, book)).toBe('user:nour.alamin@ · deepsales/*');
    const deny = change({
      action: 'grant.create',
      object_type: 'grant',
      object_id: 'g-3',
      after: { subject_type: 'group', subject_id: G, effect: 'deny', target: 'deepsales/*' },
    });
    expect(changeLabel(deny, book)).toBe('group:marketing · deny deepsales/*');
  });

  it('names a user by snapshot email, then the book, then a short id', () => {
    const boot = change({ after: { email: 'ashik@yougotagift.com', role: 'admin' } });
    expect(changeLabel(boot)).toBe('ashik@');
    expect(changeLabel(change({ after: { role: 'analyst' } }), book)).toBe('nour.alamin@');
    expect(changeLabel(change({ after: { role: 'analyst' } }))).toBe('user 3b7e0d12…');
  });

  it('names a request by short id and requester', () => {
    const approved = change({
      action: 'request.approve',
      object_type: 'access_request',
      object_id: R,
      after: { status: 'approved', user_id: U, target: 'analyst' },
    });
    expect(changeLabel(approved, book)).toBe('r-7b51 · nour.alamin@');
  });

  it('keeps unknown object types readable', () => {
    expect(changeLabel(change({ object_type: 'token', object_id: G }))).toBe('token 6f1c2a90…');
  });
});
