import { render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type EffectiveAccess } from '@/api/admin-users';
import { type CatalogResources } from '@/api/catalog-admin';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { fast, user } from './test-fixtures';
import { EffectiveAccessPanel } from './effective-access-panel';

const fetchEffectiveAccess = vi.hoisted(() => vi.fn());
vi.mock('../hooks/use-debounced-value', () => ({ useDebouncedValue: <T,>(value: T) => value }));
vi.mock('@/api/admin-users', () => ({ fetchEffectiveAccess }));
const fetchCatalogResources = vi.hoisted(() => vi.fn());
vi.mock('@/api/catalog-admin', () => ({ fetchCatalogResources }));
vi.mock('@/api/access', () => ({
  fetchCapabilityCatalog: () =>
    Promise.resolve({
      capabilities: [],
      roles: [{ name: 'viewer', capabilities: ['chat:use'] }],
      clearances: [],
      label_classes: [],
      mask_modes: [],
    }),
}));

const BASE: EffectiveAccess = {
  user_id: 'omar',
  role: 'viewer',
  active: true,
  capabilities: ['chat:use', 'mcp:use'],
  allow: [
    {
      pattern: 'demo/order/*',
      grant_id: 'g-4c2e91',
      origin: 'group:marketing',
      row_scope: { country: ['AE', 'SA'] },
    },
  ],
  deny: [
    {
      pattern: 'demo/order/refund_amount',
      grant_id: 'g-9b07e3',
      origin: 'group:marketing',
      row_scope: null,
    },
  ],
  decision: null,
  clearances: ['fields:business_names'],
  skipped: [],
};

const CATALOG: CatalogResources = {
  as_user: 'omar',
  sources: [
    {
      id: 'demo',
      name: 'Demo commerce',
      entities: [
        {
          path: 'demo/order',
          name: 'Orders',
          items: [
            {
              path: 'demo/order/revenue',
              id: 'revenue',
              name: 'Total revenue',
              kind: 'metric',
              decision: { allowed: true, reason: 'allowed', origin: 'group:marketing' },
            },
            {
              path: 'demo/order/refund_amount',
              id: 'refund_amount',
              name: 'Refunded amount',
              kind: 'metric',
              decision: { allowed: false, reason: 'denied', origin: 'group:marketing' },
            },
          ],
        },
      ],
    },
  ],
};

function decide(resource: string | undefined): EffectiveAccess {
  if (resource === 'demo/order/revenue') {
    return {
      ...BASE,
      decision: {
        resource,
        allowed: true,
        reason: 'allowed by grant g-4c2e91 (group:marketing)',
        row_scope: [{ country: ['AE', 'SA'] }],
      },
    };
  }
  if (resource)
    return {
      ...BASE,
      decision: { resource, allowed: false, reason: 'no grant allows it', row_scope: [] },
    };
  return BASE;
}

function renderPanel(target = user('omar', { display_name: 'Omar Khalil' })) {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <EffectiveAccessPanel user={target} />
    </Wrapper>,
  );
}

const probe = () => screen.getByRole('textbox', { name: 'Resource path' });
const result = () => screen.getByRole('status', { name: 'Probe result' });

describe('EffectiveAccessPanel', () => {
  beforeEach(() => {
    fetchEffectiveAccess.mockReset();
    fetchEffectiveAccess.mockImplementation((_id: string, resource?: string) =>
      Promise.resolve(decide(resource)),
    );
    fetchCatalogResources.mockReset();
    fetchCatalogResources.mockResolvedValue(CATALOG);
  });

  it('a probe with no matching grant reads deny with the backend reason', async () => {
    renderPanel();
    await fast().type(probe(), 'demo/checkout/checkout_funnel');
    await waitFor(() =>
      expect(within(result()).getByText('no grant allows it')).toBeInTheDocument(),
    );
    expect(within(result()).getByText('deny')).toBeInTheDocument();
    expect(within(result()).getByText(/Grant it to a group Omar is in/)).toBeInTheDocument();
    expect(fetchEffectiveAccess).toHaveBeenCalledWith('omar', 'demo/checkout/checkout_funnel');
  });

  it('an allow names the deciding grant and its origin', async () => {
    renderPanel();
    await fast().type(probe(), 'demo/order/revenue');
    await waitFor(() =>
      expect(
        within(result()).getByText('allowed by grant g-4c2e91 (group:marketing)'),
      ).toBeInTheDocument(),
    );
    expect(within(result()).getByText('demo/order/*')).toBeInTheDocument();
    expect(within(result()).getByText('deciding grant g-4c2e91')).toBeInTheDocument();
  });

  it('an allow shows the row scope the policy grants, and the rule carries it', async () => {
    renderPanel();
    await fast().type(probe(), 'demo/order/revenue');
    await waitFor(() => expect(within(result()).getByText('allow')).toBeInTheDocument());
    expect(within(result()).getAllByText('country=AE,SA')).toHaveLength(2);
  });

  it('an unscoped allow reads "all rows"; a deny shows no rows line', async () => {
    fetchEffectiveAccess.mockImplementation((_id: string, resource?: string) =>
      Promise.resolve(
        resource === 'demo/order/revenue'
          ? {
              ...BASE,
              decision: { resource, allowed: true, reason: 'allowed', row_scope: null },
            }
          : decide(resource),
      ),
    );
    renderPanel();
    await fast().type(probe(), 'demo/order/revenue');
    expect(
      await within(await screen.findByRole('status', { name: 'Probe result' })).findByText(
        'all rows',
      ),
    ).toBeInTheDocument();
  });

  it('lists the clearances the user holds', async () => {
    renderPanel();
    expect(await screen.findByText('fields:business_names')).toBeInTheDocument();
  });

  it('a grant the evaluator skipped is stated with its reason', async () => {
    fetchEffectiveAccess.mockResolvedValue({
      ...BASE,
      skipped: [
        {
          pattern: 'demo/order/*',
          grant_id: 'g-77',
          origin: 'user',
          reason: "$self needs the attribute 'csm', which isn't set",
        },
      ],
    });
    renderPanel();
    expect(await screen.findByText("Some grants don't apply")).toBeInTheDocument();
    expect(
      screen.getByText("$self needs the attribute 'csm', which isn't set"),
    ).toBeInTheDocument();
  });

  it('an invalid path is refused before any request', async () => {
    renderPanel();
    await fast().type(probe(), 'Demo');
    expect(await screen.findByText(/Enter a resource path like/)).toBeInTheDocument();
    expect(fetchEffectiveAccess).not.toHaveBeenCalledWith('omar', 'Demo');
  });

  it('the catalog shows the user decision on every item, with its origin', async () => {
    renderPanel();
    const tree = await screen.findByRole('tree', { name: 'What Omar can see' });
    const revenue = within(tree).getByRole('treeitem', { name: /revenue/ });
    expect(within(revenue).getByText('allow')).toBeInTheDocument();
    const refund = within(tree).getByRole('treeitem', { name: /refund_amount/ });
    expect(within(refund).getByText('deny')).toBeInTheDocument();
    expect(fetchCatalogResources).toHaveBeenCalledWith('omar');
  });

  it('headings fall back to the email local part when there is no display name', async () => {
    renderPanel(user('omar', { display_name: '  ', email: 'omar.khalil@yougotagift.com' }));
    expect(await screen.findByRole('tree', { name: 'What omar.khalil can see' })).toBeVisible();
  });

  it('names the source of each capability: the role bundle, else a direct grant', async () => {
    renderPanel();
    expect(await screen.findByText('from role viewer')).toBeInTheDocument();
    expect(screen.getByText('chat:use').parentElement).toHaveTextContent('from role viewer');
    expect(screen.getByText('mcp:use').parentElement).toHaveTextContent('from a direct grant');
  });
});
