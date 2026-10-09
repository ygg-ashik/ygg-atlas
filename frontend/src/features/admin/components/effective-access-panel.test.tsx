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
    Promise.resolve({ capabilities: [], roles: [{ name: 'viewer', capabilities: ['chat:use'] }] }),
}));

const BASE: EffectiveAccess = {
  user_id: 'omar',
  role: 'viewer',
  active: true,
  capabilities: ['chat:use', 'mcp:use'],
  allow: [{ pattern: 'demo/order/*', grant_id: 'g-4c2e91', origin: 'group:marketing' }],
  deny: [{ pattern: 'demo/order/refund_amount', grant_id: 'g-9b07e3', origin: 'group:marketing' }],
  decision: null,
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
      },
    };
  }
  if (resource)
    return { ...BASE, decision: { resource, allowed: false, reason: 'no grant allows it' } };
  return BASE;
}

function renderPanel() {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <EffectiveAccessPanel user={user('omar', { display_name: 'Omar Khalil' })} />
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

  it('names the source of each capability: the role bundle, else a direct grant', async () => {
    renderPanel();
    expect(await screen.findByText('from role viewer')).toBeInTheDocument();
    expect(screen.getByText('chat:use').parentElement).toHaveTextContent('from role viewer');
    expect(screen.getByText('mcp:use').parentElement).toHaveTextContent('from a direct grant');
  });
});
