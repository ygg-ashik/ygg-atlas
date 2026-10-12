// Route smoke test: every settings route resolves through its guard.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type MeAccess } from '@/api/access';
import { ThemeProvider } from '@/lib/theme-provider';
import { AppRoutes } from './App';

const fetchMyAccess = vi.hoisted(() => vi.fn<() => Promise<MeAccess>>());
vi.mock('@/api/access', () => ({
  fetchMyAccess,
  fetchCapabilityCatalog: () => Promise.resolve({ capabilities: [], roles: [] }),
}));
vi.mock('@/api/access-requests', () => ({
  listMyRequests: () => Promise.resolve([]),
  listDecidableRequests: () => Promise.resolve({ items: [], next_cursor: null }),
}));
vi.mock('@/lib/firebase', () => ({ auth: {}, googleProvider: {} }));
vi.mock('@/features/auth/auth-context', () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
  useAuth: () => ({
    user: { uid: 'u1', name: 'Omar Saleh', email: 'omar@yougotagift.com', avatar: '' },
    isAuthenticated: true,
    isLoading: false,
    signOut: vi.fn(),
  }),
}));
vi.mock('@/api/hooks/use-chat-sessions', () => ({
  useChatSessions: () => ({ data: [] }),
  useDeleteChatSession: () => ({ mutate: vi.fn() }),
  useCreateChatSession: () => ({ mutateAsync: vi.fn() }),
  useChatMessages: () => ({ data: [] }),
}));
vi.mock('@/api/hooks/use-overview', () => ({
  useOverview: () => ({ data: undefined, isLoading: true, isError: false }),
}));
vi.mock('@/api/hooks/use-atlas', () => ({ useMetricsCatalog: () => ({ data: undefined }) }));
// Admin pages read these clients; the smoke test never reaches the network.
vi.mock('@/api/admin-users', () => ({
  listUsers: () => Promise.resolve({ items: [], next_cursor: null }),
  fetchUserDetail: () => new Promise(() => {}),
}));
vi.mock('@/api/admin-groups', () => {
  const g1 = { id: 'g-1', name: 'marketing', description: '', parent_id: null, created_at: '' };
  return {
    listGroups: () => Promise.resolve([g1]),
    fetchGroupDetail: () =>
      Promise.resolve({ ...g1, member_count: 0, grant_count: 0, path: ['marketing'] }),
    listMembers: () => Promise.resolve([]),
    listGrants: () => Promise.resolve([]),
  };
});
vi.mock('@/api/audit', () => ({
  listChanges: () => Promise.resolve({ items: [], next_cursor: null }),
  listDecisions: () => Promise.resolve({ items: [], next_cursor: null }),
  fetchAuditSummary: () => new Promise(() => {}),
}));
vi.mock('@/api/tokens', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  fetchAuthMethods: () => Promise.reject(new Error('offline')),
  listMyTokens: () => Promise.resolve([]),
  listConnectedApps: () => Promise.resolve([]),
  listAdminTokens: () => Promise.resolve([]),
  listClients: () => Promise.resolve([]),
}));
vi.mock('@/api/catalog-admin', () => ({
  fetchCatalogResources: () => Promise.resolve({ sources: [] }),
}));

const VIEWER: MeAccess = {
  role: 'viewer',
  capabilities: ['chat:use'],
  groups: [],
  has_data_access: true,
  user_id: 'u1',
  email: 'omar@yougotagift.com',
  display_name: 'Omar Saleh',
  pending_requests: 1,
  pending_approvals: 0,
  is_manager: false,
  clearances: [],
};
const ADMIN: MeAccess = {
  ...VIEWER,
  role: 'admin',
  capabilities: [
    'chat:use',
    'tokens:create',
    'admin:users',
    'admin:groups',
    'admin:audit',
    'admin:tokens',
    'admin:clients',
  ],
  pending_approvals: 4,
};

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const pageTitle = (name: string) => screen.findByRole('heading', { level: 2, name });

const sidebar = () => screen.getByRole('complementary');

describe('App routes', () => {
  beforeEach(() => {
    fetchMyAccess.mockReset().mockResolvedValue(ADMIN);
  });

  it.each([
    ['/settings', 'General'],
    ['/settings/access', 'My access'],
    ['/settings/requests', 'Requests'],
    ['/settings/requests/new?kind=role', 'Request access'],
    ['/settings/tokens', 'Tokens & connected apps'],
    ['/settings/admin/users', 'Users'],
    ['/settings/admin/groups', 'Groups'],
    ['/settings/admin/groups/g-1', 'Groups'],
    ['/settings/admin/requests', 'Access requests'],
    ['/settings/admin/audit', 'Audit'],
    ['/settings/admin/tokens', 'Tokens'],
    ['/settings/admin/clients', 'OAuth clients'],
  ])('%s renders its page for an admin', async (path, title) => {
    renderAt(path);
    expect(await pageTitle(title)).toBeInTheDocument();
    expect(document.querySelector('[data-route-label]')).toHaveTextContent(path.split('?')[0]!);
  });

  it('/settings/admin/users/u-9 renders the user page for an admin', async () => {
    renderAt('/settings/admin/users/u-9');
    expect(await screen.findByRole('heading', { level: 1, name: 'User' })).toBeInTheDocument();
    expect(document.querySelector('[data-route-label]')).toHaveTextContent(
      '/settings/admin/users/u-9',
    );
  });

  it.each([
    ['/', 'Overview'],
    ['/ask', 'New chat'],
    ['/metrics', 'Metrics'],
  ])('%s renders its unguarded page for a viewer', async (path, title) => {
    fetchMyAccess.mockResolvedValue(VIEWER);
    renderAt(path);
    expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument();
  });

  it.each(['/account', '/account/tokens', '/admin', '/admin/users'])(
    'the retired %s is not a route: it falls to the catch-all home',
    async (path) => {
      renderAt(path);
      expect(
        await screen.findByRole('heading', { level: 1, name: 'Overview' }),
      ).toBeInTheDocument();
      expect(document.querySelector('[data-route-label]')).not.toBeInTheDocument();
    },
  );

  it('a first sign-in with no data access gets the chat with the first-run state', async () => {
    fetchMyAccess.mockResolvedValue({ ...VIEWER, has_data_access: false });
    renderAt('/');
    expect(
      await screen.findByRole('heading', { level: 2, name: 'Welcome to Atlas, Omar' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'No data access yet' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'New chat' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2, name: 'My access' })).toBeNull();
  });

  it('first run: Request access opens the request dialog over the chat', async () => {
    fetchMyAccess.mockResolvedValue({ ...VIEWER, has_data_access: false });
    renderAt('/');
    await userEvent.click(await screen.findByRole('link', { name: 'Request access' }));
    const dialog = await screen.findByRole('dialog', { name: 'Request access' });
    expect(within(dialog).getByRole('radio', { name: 'Group' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    // The chat stays underneath, hidden from assistive tech while the dialog is up.
    expect(
      screen.getByRole('heading', { name: 'No data access yet', hidden: true }),
    ).toBeInTheDocument();
  });

  it('shows a skeleton on / while access loads', () => {
    fetchMyAccess.mockReturnValue(new Promise(() => {}));
    renderAt('/');
    expect(screen.getByRole('status')).toHaveTextContent('Loading your workspace');
  });

  it('an admin without data access still lands on Overview', async () => {
    fetchMyAccess.mockResolvedValue({ ...ADMIN, has_data_access: false });
    renderAt('/');
    expect(await screen.findByRole('heading', { level: 1, name: 'Overview' })).toBeInTheDocument();
  });

  it('a viewer deep-linking an Organization page gets the denied page, no Organization rail', async () => {
    fetchMyAccess.mockResolvedValue(VIEWER);
    renderAt('/settings/admin/users');
    const denied = await screen.findByRole('region', { name: 'This area needs admin:users' });
    expect(denied).toHaveTextContent('Your role (viewer)');
    expect(within(denied).getByRole('link', { name: 'Go to My access' })).toHaveAttribute(
      'href',
      '/settings/access',
    );
    expect(within(denied).getByRole('link', { name: 'Request access' })).toHaveAttribute(
      'href',
      '/settings/requests/new?kind=role',
    );
    expect(document.querySelector('[data-route-label]')).toHaveTextContent('/settings/admin/users');
    expect(within(sidebar()).getByRole('group', { name: 'You' })).toBeInTheDocument();
    expect(within(sidebar()).queryByRole('group', { name: 'Organization' })).toBeNull();
  });

  it('an admin:tokens-only persona opens Tokens but not OAuth clients', async () => {
    fetchMyAccess.mockResolvedValue({ ...VIEWER, capabilities: ['chat:use', 'admin:tokens'] });
    renderAt('/settings/admin/clients');
    expect(
      await screen.findByRole('region', { name: 'This area needs admin:clients' }),
    ).toBeInTheDocument();
    const org = within(sidebar()).getByRole('group', { name: 'Organization' });
    expect(
      within(org)
        .getAllByRole('link')
        .map((l) => l.getAttribute('href')),
    ).toEqual(['/settings/admin/tokens']);
  });

  it('a failed access answer renders the denied page, never the Organization page', async () => {
    fetchMyAccess.mockRejectedValue(new Error('503'));
    renderAt('/settings/admin/audit');
    expect(
      await screen.findByRole('region', { name: 'This area needs admin:audit' }),
    ).toHaveTextContent('Your role (unconfirmed)');
    expect(screen.queryByRole('heading', { level: 2, name: 'Audit' })).not.toBeInTheDocument();
  });

  it('an admin sees the Organization rail with the approvals badge', async () => {
    renderAt('/settings/access');
    const org = await within(sidebar()).findByRole('group', { name: 'Organization' });
    expect(within(org).getByRole('link', { name: /Access requests/ })).toHaveTextContent(
      '4 requests to decide',
    );
  });

  it('the account menu offers Admin and the chip a dot for an admin with approvals', async () => {
    renderAt('/ask');
    const chip = within(sidebar()).getByRole('button', { name: /^Account menu/ });
    expect(await within(chip).findByRole('img', { name: '4 pending approvals' })).toBeVisible();
    await userEvent.click(chip);
    const menu = await screen.findByRole('menu');
    expect(within(menu).getByRole('menuitem', { name: /Admin/ })).toHaveAttribute(
      'href',
      '/settings/admin/requests',
    );
  });

  it('a viewer gets no Admin item', async () => {
    fetchMyAccess.mockResolvedValue(VIEWER);
    renderAt('/ask');
    await screen.findByRole('heading', { level: 1, name: 'New chat' });
    await userEvent.click(within(sidebar()).getByRole('button', { name: /^Account menu/ }));
    const menu = await screen.findByRole('menu');
    expect(within(menu).queryByRole('menuitem', { name: /Admin/ })).toBeNull();
  });

  it('the command palette offers only the pages the viewer can open', async () => {
    fetchMyAccess.mockResolvedValue(VIEWER);
    renderAt('/settings/access');
    await pageTitle('My access');
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const palette = await screen.findByRole('dialog');
    expect(
      within(palette).getByRole('option', { name: /Settings › My access/ }),
    ).toBeInTheDocument();
    expect(within(palette).queryByRole('option', { name: /Settings › Users/ })).toBeNull();
  });
});
