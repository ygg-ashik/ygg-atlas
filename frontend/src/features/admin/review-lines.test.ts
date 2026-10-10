import { describe, expect, it } from 'vitest';
import {
  attributeLines,
  clientRevokeLines,
  grantCreateLines,
  labelClassLines,
  memberPutLines,
  revokeAllLines,
  roleChangeLines,
  statusChangeLines,
  tokenRevokeLines,
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
      'scope     all rows',
    ]);
  });

  it('a new member goes from — to member', () => {
    const lines = memberPutLines('csm', 'sara@x.com', null, 'member');
    expect(lines.slice(2)).toEqual([
      { kind: 'remove', text: 'standing  —' },
      { kind: 'add', text: 'standing  member' },
    ]);
  });

  it('revoke all never claims connected apps keep working', () => {
    const pat = { prefix: 'atl_pat_1', name: 'laptop', kind: 'pat' };
    const oauth = { prefix: 'atl_oat_2', name: 'Claude', kind: 'oauth_access' };
    const patOnly = revokeAllLines('a@x.com', [pat]).map((l) => l.text);
    expect(patOnly.join('\n')).not.toMatch(/keep working/);
    expect(patOnly.at(-1)).toBe('every live token of any kind; each gets 401 on its next call');
    const withApps = revokeAllLines('a@x.com', [pat, oauth]).map((l) => l.text);
    expect(withApps).toContain('token     atl_oat_2…  Claude');
    expect(withApps.at(-1)).toBe('connected apps lose access too: their OAuth tokens are revoked');
  });

  it('attribute writes name the actions AccessAdmin records', () => {
    expect(attributeLines('a@x.com', 'country', null, 'AE')[0]?.text).toBe(
      'attribute.set  a@x.com',
    );
    expect(attributeLines('a@x.com', 'country', 'AE', null)[0]?.text).toBe(
      'attribute.delete  a@x.com',
    );
  });

  it('a label class change lists only the fields that move', () => {
    const current = {
      label_class: 'person_name',
      mode: 'suppress' as const,
      bucket_size: 5,
      updated_at: '2026-10-01T00:00:00Z',
    };
    expect(labelClassLines(current, { mode: 'pseudonymise' }).map((l) => l.text)).toEqual([
      'label_class.update  person_name',
      'mode      suppress',
      'mode      pseudonymise',
      'applies to every caller without the matching clearance',
    ]);
  });
});

describe('credential review lines name the credential_events event', () => {
  it('token, revoke-all and client revokes', () => {
    const token = { prefix: 'atl_pat_1', name: 'laptop' };
    expect(tokenRevokeLines(token)[0]?.text).toBe('token.revoked');
    expect(revokeAllLines('a@x.com', [token])[0]?.text).toBe('tokens.revoked_all  a@x.com');
    expect(clientRevokeLines({ client_id: 'oc_1', client_name: 'Claude' }, 2)[0]?.text).toBe(
      'client.revoked  oc_1',
    );
  });
});
