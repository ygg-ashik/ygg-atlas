// Settings navigation per persona: the rail's Organization group, the account
// menu's Admin entry and the palette's pages all come from `/me/access`.
import { describe, expect, it, vi } from 'vitest';
import { type MyAccessView } from '@/api/hooks/use-my-access';
import { accessView, PERSONAS } from '@/test/access-view';
import { adminEntry, buildPalettePages, buildSettingsNav, PRIMARY_NAV } from './navigation';

// The auth barrel pulls in the Firebase SDK; nothing here signs in.
vi.mock('@/lib/firebase', () => ({ auth: {}, googleProvider: {} }));

const paths = (view: MyAccessView, title: string) =>
  buildSettingsNav(view)
    .find((s) => s.title === title)
    ?.items.map((i) => i.to);

const YOU = ['/settings', '/settings/access', '/settings/requests', '/settings/tokens'];

describe('primary nav', () => {
  it('holds only the work: Overview, Ask Atlas, Metrics', () => {
    expect(PRIMARY_NAV.map((i) => i.to)).toEqual(['/', '/ask', '/metrics']);
  });
});

describe('settings rail per persona', () => {
  it('new viewer: You only, no Organization', () => {
    expect(paths(PERSONAS.newViewer, 'You')).toEqual(YOU);
    expect(paths(PERSONAS.newViewer, 'Organization')).toBeUndefined();
  });

  it('manager: Groups and Access requests, the queue badged with pending_approvals', () => {
    expect(paths(PERSONAS.manager, 'Organization')).toEqual([
      '/settings/admin/groups',
      '/settings/admin/requests',
    ]);
    const queue = buildSettingsNav(PERSONAS.manager)[1]?.items[1];
    expect(queue?.badge).toEqual({ count: 3, label: 'requests to decide' });
  });

  it('admin: every Organization page their capabilities open', () => {
    expect(paths(PERSONAS.admin, 'Organization')).toEqual([
      '/settings/admin/users',
      '/settings/admin/groups',
      '/settings/admin/requests',
      '/settings/admin/audit',
    ]);
  });

  it('admin:tokens and admin:clients each open only their own page', () => {
    expect(
      paths(accessView({ capabilities: ['chat:use', 'admin:tokens'] }), 'Organization'),
    ).toEqual(['/settings/admin/tokens']);
    expect(
      paths(accessView({ capabilities: ['chat:use', 'admin:clients'] }), 'Organization'),
    ).toEqual(['/settings/admin/clients']);
  });

  it('one request to decide reads in the singular', () => {
    const view = accessView({ is_manager: true, pending_approvals: 1 });
    expect(buildSettingsNav(view)[1]?.items[1]?.badge?.label).toBe('request to decide');
  });

  it.each(['loading', 'unavailable'] as const)('%s access: no Organization (fail closed)', (s) => {
    expect(paths(accessView({}, s), 'Organization')).toBeUndefined();
    expect(paths(accessView({}, s), 'You')).toEqual(YOU);
  });
});

describe('account menu Admin entry', () => {
  it('is absent for viewers and for capabilities outside admin', () => {
    expect(adminEntry(PERSONAS.newViewer)).toBeUndefined();
    expect(adminEntry(PERSONAS.viewer)).toBeUndefined();
    expect(
      adminEntry(accessView({ capabilities: ['chat:use', 'mcp:use', 'tokens:create'] })),
    ).toBeUndefined();
  });

  it('opens the queue when something waits, with the count', () => {
    expect(adminEntry(PERSONAS.manager)).toEqual({
      to: '/settings/admin/requests',
      pendingApprovals: 3,
    });
    expect(adminEntry(PERSONAS.admin)).toEqual({
      to: '/settings/admin/requests',
      pendingApprovals: 5,
    });
  });

  it('otherwise opens the first Organization page', () => {
    expect(adminEntry({ ...PERSONAS.admin, pendingApprovals: 0 })?.to).toBe(
      '/settings/admin/users',
    );
    expect(adminEntry(accessView({ is_manager: true }))?.to).toBe('/settings/admin/groups');
    expect(adminEntry(accessView({ capabilities: ['chat:use', 'admin:audit'] }))?.to).toBe(
      '/settings/admin/audit',
    );
  });

  it.each(['loading', 'unavailable'] as const)('is absent while access is %s', (s) => {
    expect(adminEntry(accessView({ capabilities: ['admin:users'] }, s))).toBeUndefined();
  });
});

describe('palette pages', () => {
  it('offers the primary pages and Settings pages the viewer can open', () => {
    const pages = buildPalettePages(PERSONAS.viewer);
    expect(pages.map((p) => p.label)).toEqual([
      'Overview',
      'Ask Atlas',
      'Metrics',
      'Settings › General',
      'Settings › My access',
      'Settings › Requests',
      'Settings › Tokens & apps',
    ]);
  });

  it('adds Organization pages for an admin', () => {
    const labels = buildPalettePages(PERSONAS.admin).map((p) => p.label);
    expect(labels).toContain('Settings › Users');
    expect(labels).not.toContain('Settings › OAuth clients');
  });
});
