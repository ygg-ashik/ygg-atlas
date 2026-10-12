import { describe, expect, it } from 'vitest';
import {
  ROUTES,
  adminGroupPath,
  adminUserPath,
  askPath,
  consentRequestPath,
  deniedRequestPath,
  isSettingsPath,
  metricPath,
  newRequestPath,
  threadPath,
} from './routes';

describe('ROUTES', () => {
  it('puts every settings page under /settings', () => {
    expect(ROUTES).toMatchObject({
      settings: '/settings',
      access: '/settings/access',
      requests: '/settings/requests',
      newRequest: '/settings/requests/new',
      tokens: '/settings/tokens',
      adminUsers: '/settings/admin/users',
      adminUser: '/settings/admin/users/:id',
      adminGroups: '/settings/admin/groups',
      adminGroup: '/settings/admin/groups/:id',
      adminRequests: '/settings/admin/requests',
      adminAudit: '/settings/admin/audit',
      adminTokens: '/settings/admin/tokens',
      adminClients: '/settings/admin/clients',
    });
  });

  it('keeps no route under the retired /account or /admin roots', () => {
    for (const path of Object.values(ROUTES)) {
      expect(path).not.toMatch(/^\/(account|admin)(\/|$)/);
    }
  });
});

describe('path builders', () => {
  it('fills and encodes detail ids', () => {
    expect(adminUserPath('u-9')).toBe('/settings/admin/users/u-9');
    expect(adminUserPath('svc:ci bot')).toBe('/settings/admin/users/svc%3Aci%20bot');
    expect(adminGroupPath('g-1')).toBe('/settings/admin/groups/g-1');
    expect(threadPath('s1')).toBe('/ask/s1');
  });

  it('builds the ask and metric deep links', () => {
    expect(askPath('why did aov drop?')).toBe('/ask?q=why%20did%20aov%20drop%3F');
    expect(metricPath('revenue')).toBe('/metrics#metric-revenue');
  });

  it('builds the new-request link with only the prefill it is given', () => {
    expect(newRequestPath()).toBe('/settings/requests/new');
    expect(newRequestPath({ kind: 'group' })).toBe('/settings/requests/new?kind=group');
  });

  it('the denied block asks for its exact resource, labelled', () => {
    expect(deniedRequestPath('demo/checkout/checkout_funnel', 'Checkout funnel & more')).toBe(
      '/settings/requests/new?resource=demo%2Fcheckout%2Fcheckout_funnel&label=Checkout+funnel+%26+more',
    );
  });

  it('the consent page asks for a role', () => {
    expect(consentRequestPath()).toBe('/settings/requests/new?kind=role');
  });
});

describe('isSettingsPath', () => {
  it.each([
    ['/settings', true],
    ['/settings/admin/users/u-9', true],
    ['/settingsx', false],
    ['/ask', false],
    ['/', false],
  ])('%s → %s', (path, expected) => {
    expect(isSettingsPath(path)).toBe(expected);
  });
});
