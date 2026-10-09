// Test-only fixtures for the admin feature. Imported only by *.test.tsx.
import userEvent from '@testing-library/user-event';
import { type CapabilityCatalog } from '@/api/access';
import { type GrantOut, type Group, type Member } from '@/api/admin-groups';
import { type User, type UserDetail } from '@/api/admin-users';

export const CATALOG: CapabilityCatalog = {
  capabilities: [],
  roles: [
    { name: 'viewer', capabilities: ['chat:use'] },
    { name: 'analyst', capabilities: ['chat:use', 'mcp:use', 'tokens:create'] },
    { name: 'builder', capabilities: ['chat:use', 'mcp:use', 'tokens:create', 'artifacts:save'] },
    {
      name: 'admin',
      capabilities: ['chat:use', 'mcp:use', 'admin:users', 'admin:groups', 'admin:audit'],
    },
  ],
};

export function user(id: string, overrides: Partial<User> = {}): User {
  return {
    id,
    email: `${id}@yougotagift.com`,
    display_name: id.charAt(0).toUpperCase() + id.slice(1),
    kind: 'human',
    role: 'viewer',
    status: 'active',
    last_seen_at: '2026-10-09T09:47:00Z',
    created_at: '2026-09-24T00:00:00Z',
    ...overrides,
  };
}

export function grant(id: string, overrides: Partial<GrantOut> = {}): GrantOut {
  return {
    id,
    subject_type: 'group',
    subject_id: 'g-m',
    effect: 'allow',
    target_kind: 'resource',
    target: 'demo/order/*',
    reason: '',
    expires_at: null,
    created_by: null,
    created_at: '2026-09-24T00:00:00Z',
    ...overrides,
  };
}

export function detail(id: string, overrides: Partial<UserDetail> = {}): UserDetail {
  return { ...user(id), groups: [], direct_grants: [], pending_requests: 0, ...overrides };
}

export function group(id: string, name: string, parent: string | null = null): Group {
  return {
    id,
    name,
    description: `${name} team`,
    parent_id: parent,
    created_at: '2026-09-23T00:00:00Z',
  };
}

export function member(id: string, standing: 'member' | 'manager' = 'member'): Member {
  return {
    user_id: id,
    email: `${id}@yougotagift.com`,
    display_name: id.charAt(0).toUpperCase() + id.slice(1),
    standing,
    added_at: '2026-09-24T00:00:00Z',
    role: 'viewer',
    status: 'active',
  };
}

/** A review card's diff as [kind, text] pairs, without the visible marks. */
export function diffLines(region: HTMLElement): [string | null, string][] {
  return Array.from(region.querySelectorAll('[data-kind]')).map((el) => [
    el.getAttribute('data-kind'),
    (el.textContent ?? '').replace(/^(\+ |− | {2})(added: |removed: )?/, ''),
  ]);
}

/** userEvent without per-keystroke delays: these tests drive many keys and clicks. */
export const fast = () => userEvent.setup({ delay: null });
