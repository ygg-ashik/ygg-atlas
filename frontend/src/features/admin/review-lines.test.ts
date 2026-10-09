import { describe, expect, it } from 'vitest';
import {
  grantCreateLines,
  memberPutLines,
  roleChangeLines,
  statusChangeLines,
} from './review-lines';

const ROLES = [
  { name: 'viewer', capabilities: ['chat:use'] },
  { name: 'analyst', capabilities: ['chat:use', 'mcp:use'] },
];

describe('review lines mirror the rbac_changes row', () => {
  it('a role change shows before → after and the capabilities gained', () => {
    expect(roleChangeLines('omar@x.com', 'viewer', 'analyst', ROLES)).toEqual([
      { kind: 'context', text: 'user.role  omar@x.com' },
      { kind: 'remove', text: 'role      viewer' },
      { kind: 'add', text: 'role      analyst' },
      { kind: 'context', text: 'gains     mcp:use' },
    ]);
  });

  it('a demotion lists what is lost', () => {
    const lines = roleChangeLines('a@x.com', 'analyst', 'viewer', ROLES);
    expect(lines.at(-1)).toEqual({ kind: 'context', text: 'loses     mcp:use' });
  });

  it('a status change', () => {
    expect(statusChangeLines('a@x.com', 'active', 'disabled').slice(1, 3)).toEqual([
      { kind: 'remove', text: 'status    active' },
      { kind: 'add', text: 'status    disabled' },
    ]);
  });

  it('a grant create lists every stored field', () => {
    const lines = grantCreateLines('group:marketing', {
      effect: 'allow',
      target_kind: 'resource',
      target: 'demo/checkout/*',
      reason: '',
      expires_at: null,
    });
    expect(lines.map((l) => l.text)).toEqual([
      'grant.create  group:marketing',
      'effect    allow',
      'target    demo/checkout/*',
      'expires   —',
    ]);
  });

  it('a new member goes from — to member', () => {
    const lines = memberPutLines('csm', 'sara@x.com', null, 'member');
    expect(lines.slice(2)).toEqual([
      { kind: 'remove', text: 'standing  —' },
      { kind: 'add', text: 'standing  member' },
    ]);
  });
});
