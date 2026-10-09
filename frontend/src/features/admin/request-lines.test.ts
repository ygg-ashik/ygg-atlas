import { describe, expect, it } from 'vitest';
import { type AccessRequest } from '@/api/access-requests';
import { approveLines, NO_CHANGE_IF_HELD } from './request-lines';

const ROLES = [
  { name: 'viewer', capabilities: ['chat:use'] },
  { name: 'analyst', capabilities: ['chat:use', 'mcp:use'] },
  { name: 'builder', capabilities: ['chat:use', 'mcp:use', 'alerts:manage'] },
];

function req(overrides: Partial<AccessRequest>): AccessRequest {
  return {
    id: 'abcdef12-0000',
    kind: 'group',
    target: 'g-m',
    target_label: 'marketing',
    note: 'Joining.',
    status: 'pending',
    created_at: '2026-10-09T09:46:00Z',
    decided_by: null,
    decided_at: null,
    decision_note: '',
    requester: { user_id: 'u', email: 'omar@x.com', display_name: 'Omar', role: 'analyst' },
    ...overrides,
  };
}

const texts = (r: AccessRequest, expiry = '') =>
  approveLines(r, { expiry, roles: ROLES }).map((l) => `${l.kind}:${l.text}`);

describe('approveLines never promises a write the backend skips', () => {
  it('group: the member add, plus "no change if already a member"', () => {
    expect(texts(req({}))).toEqual([
      'context:request abcdef12  omar@x.com',
      'add:member omar@x.com in marketing',
      `context:${NO_CHANGE_IF_HELD.group}`,
    ]);
  });

  it('role upgrade: the change, its gains, and the already-held note', () => {
    expect(texts(req({ kind: 'role', target: 'builder', target_label: 'builder' }))).toEqual([
      'context:request abcdef12  omar@x.com',
      'add:role analyst → builder',
      'context:gains     alerts:manage',
      `context:${NO_CHANGE_IF_HELD.role}`,
    ]);
  });

  it('role already at or above the target: records the decision only, no add line', () => {
    const lines = texts(req({ kind: 'role', target: 'viewer', target_label: 'viewer' }));
    expect(lines).toEqual([
      'context:request abcdef12  omar@x.com',
      'context:role analyst already at or above viewer: records the decision only',
    ]);
    const same = approveLines(req({ kind: 'role', target: 'analyst' }), {
      expiry: '',
      roles: ROLES,
    });
    expect(same.some((l) => l.kind === 'add')).toBe(false);
  });

  it('role with no catalog yet: shows the change with the hedge', () => {
    const lines = approveLines(req({ kind: 'role', target: 'viewer' }), { expiry: '', roles: [] });
    expect(lines.map((l) => l.text)).toContain('role analyst → viewer');
    expect(lines.at(-1)?.text).toBe(NO_CHANGE_IF_HELD.role);
  });

  it('resource: the grant, its reason, and the already-held note', () => {
    const lines = texts(req({ kind: 'resource', target: 'demo/x/y' }), '2027-01-07');
    expect(lines[1]).toBe('add:grant allow demo/x/y for omar@x.com until 2027-01-07');
    expect(lines.at(-1)).toBe(`context:${NO_CHANGE_IF_HELD.resource}`);
  });
});
