import { describe, expect, it } from 'vitest';
import {
  addedCapabilities,
  approverText,
  buildRequest,
  initialRequest,
  isResourcePath,
  MAX_NOTE,
  nextRole,
  noteError,
  requestableRoles,
} from './request-rules';

const ROLES = [
  { name: 'viewer', capabilities: ['chat:use'] },
  { name: 'analyst', capabilities: ['chat:use', 'mcp:use', 'tokens:create'] },
  { name: 'builder', capabilities: ['chat:use', 'mcp:use', 'tokens:create', 'atlas:build'] },
  { name: 'admin', capabilities: ['chat:use', 'admin:users'] },
];

describe('isResourcePath (mirrors backend patterns.is_resource_path)', () => {
  it.each([
    ['demo/order', true],
    ['demo/checkout/checkout_funnel', true],
    ['deepsales/ds_account/arr_2', true],
    ['demo', false],
    ['demo/*', false],
    ['*', false],
    ['demo/order/revenue/x', false],
    ['Demo/order', false],
    ['demo//order', false],
    ['demo/order-x', false],
    ['', false],
  ])('%s → %s', (path, ok) => {
    expect(isResourcePath(path)).toBe(ok);
  });
});

describe('initialRequest (query params)', () => {
  const parse = (q: string) => initialRequest(new URLSearchParams(q));

  it('a resource from a chat denial prefills the resource kind and its label', () => {
    expect(parse('resource=demo%2Fcheckout%2Fcheckout_funnel&label=Checkout+funnel')).toEqual({
      kind: 'resource',
      resource: 'demo/checkout/checkout_funnel',
      label: 'Checkout funnel',
    });
  });

  it('honours ?kind=role from the consent denial page', () => {
    expect(parse('kind=role')).toEqual({ kind: 'role', resource: '', label: '' });
  });

  it('defaults to group and ignores an unknown kind', () => {
    expect(parse('').kind).toBe('group');
    expect(parse('kind=superuser').kind).toBe('group');
  });

  it('an explicit kind wins over the resource default', () => {
    expect(parse('kind=group&resource=demo/order').kind).toBe('group');
  });
});

describe('noteError', () => {
  it('requires a non-blank note of at most 500 characters', () => {
    expect(noteError('', 'Sara Mansour')).toBe('Add a short note so Sara Mansour can decide.');
    expect(noteError('   ', 'an admin')).toBe('Add a short note so an admin can decide.');
    expect(noteError('x'.repeat(MAX_NOTE + 1), 'an admin')).toBe(
      'Keep the note under 500 characters.',
    );
    expect(noteError('Q4 review', 'an admin')).toBeNull();
  });
});

describe('requestableRoles (strictly above the current role)', () => {
  it('marks the current and lower roles unavailable', () => {
    expect(requestableRoles(ROLES, 'analyst')).toEqual([
      { name: 'viewer', current: false, available: false },
      { name: 'analyst', current: true, available: false },
      { name: 'builder', current: false, available: true },
      { name: 'admin', current: false, available: true },
    ]);
  });

  it('nextRole is the first role above, none for the top role', () => {
    expect(nextRole(ROLES, 'viewer')).toBe('analyst');
    expect(nextRole(ROLES, 'admin')).toBeNull();
  });

  it('an unknown current role ranks below every real one', () => {
    expect(requestableRoles(ROLES, 'ghost').every((r) => r.available)).toBe(true);
  });

  it('addedCapabilities lists what a role adds over the current one', () => {
    expect(addedCapabilities(ROLES, 'viewer', 'analyst')).toEqual(['mcp:use', 'tokens:create']);
    expect(addedCapabilities(ROLES, 'viewer', 'nope')).toEqual([]);
  });
});

describe('approverText', () => {
  it('names a chosen group’s managers, else an admin', () => {
    const groups = [
      { id: 'g1', name: 'marketing-paid', managers: ['Sara Mansour', 'Omar Saleh'] },
      { id: 'g2', name: 'risk-ops', managers: [] },
    ];
    expect(approverText(groups, 'g1')).toBe('Sara Mansour and Omar Saleh');
    expect(approverText(groups, 'g2')).toBe('an admin');
    expect(approverText(groups, 'direct')).toBe('an admin');
    expect(approverText(groups, null)).toBe('an admin');
  });
});

describe('buildRequest', () => {
  const base = { resource: 'demo/order', choice: null, role: null, note: '  Q4 review  ' };

  it('a chosen group asks to join it (group or resource kind)', () => {
    for (const kind of ['group', 'resource'] as const) {
      expect(buildRequest({ ...base, kind, choice: 'g1' }, 'an admin')).toEqual({
        ok: true,
        body: { kind: 'group', target: 'g1', note: 'Q4 review' },
      });
    }
  });

  it('direct asks for the exact resource', () => {
    expect(buildRequest({ ...base, kind: 'resource', choice: 'direct' }, 'an admin')).toEqual({
      ok: true,
      body: { kind: 'resource', target: 'demo/order', note: 'Q4 review' },
    });
  });

  it('a role request carries the role', () => {
    expect(buildRequest({ ...base, kind: 'role', role: 'analyst' }, 'an admin')).toEqual({
      ok: true,
      body: { kind: 'role', target: 'analyst', note: 'Q4 review' },
    });
  });

  it('reports every missing field at once', () => {
    expect(buildRequest({ ...base, kind: 'resource', note: '' }, 'an admin')).toEqual({
      ok: false,
      errors: {
        target: 'Pick a group, or ask for a direct grant.',
        note: 'Add a short note so an admin can decide.',
      },
    });
    expect(buildRequest({ ...base, kind: 'group' }, 'an admin')).toMatchObject({
      ok: false,
      errors: { target: 'Pick the group you want to join.' },
    });
    expect(buildRequest({ ...base, kind: 'role' }, 'an admin')).toMatchObject({
      ok: false,
      errors: { target: 'Pick the role you need.' },
    });
  });

  it('direct needs a full resource path', () => {
    expect(
      buildRequest({ ...base, kind: 'resource', resource: 'demo', choice: 'direct' }, 'x'),
    ).toMatchObject({ ok: false, errors: { target: expect.stringContaining('resource path') } });
  });
});
