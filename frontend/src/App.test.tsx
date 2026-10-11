// Route smoke test: every account and admin route resolves through its guard.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
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

describe('App routes', () => {
  beforeEach(() => {
    fetchMyAccess.mockReset().mockResolvedValue(ADMIN);
  });

  it.each([
    ['/account', 'My access'],
    ['/account/requests', 'My requests'],
    ['/account/requests/new?kind=role', 'Request access'],
    ['/account/tokens', 'Tokens & connected apps'],
    ['/admin/users', 'Users'],
    ['/admin/groups', 'Groups'],
    ['/admin/groups/g-1', 'Groups'],
    ['/admin/requests', 'Access requests'],
    ['/admin/audit', 'Audit'],
    ['/admin/tokens', 'Tokens'],
    ['/admin/clients', 'OAuth clients'],
  ])('%s renders its page for an admin', async (path, title) => {
    renderAt(path);
    expect(await pageTitle(title)).toBeInTheDocument();
    expect(document.querySelector('[data-route-label]')).toHaveTextContent(path.split('?')[0]!);
  });

  it('/admin/users/u-9 renders the user page for an admin', async () => {
    renderAt('/admin/users/u-9');
    expect(await screen.findByRole('heading', { level: 1, name: 'User' })).toBeInTheDocument();
    expect(document.querySelector('[data-route-label]')).toHaveTextContent('/admin/users/u-9');
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

  it('a first sign-in with no data access lands on My access, greeted', async () => {
    fetchMyAccess.mockResolvedValue({ ...VIEWER, has_data_access: false });
    renderAt('/');
    expect(await pageTitle('Welcome to Atlas, Omar')).toBeInTheDocument();
    expect(document.querySelector('[data-route-label]')).toHaveTextContent('/account');
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

  it('/admin itself sends the viewer home rather than to an empty admin index', async () => {
    renderAt('/admin');
    expect(await screen.findByRole('heading', { level: 1, name: 'Overview' })).toBeInTheDocument();
  });

  it('a viewer deep-linking /admin/users gets the denied page, stays on the URL, no admin chrome', async () => {
    fetchMyAccess.mockResolvedValue(VIEWER);
    renderAt('/admin/users');
    expect(
      await screen.findByRole('region', { name: 'This area needs admin:users' }),
    ).toHaveTextContent('Your role (viewer)');
    expect(document.querySelector('[data-route-label]')).toHaveTextContent('/admin/users');
    const side = screen.getByRole('complementary');
    expect(within(side).queryByRole('group', { name: 'Admin' })).not.toBeInTheDocument();
    expect(within(side).getByRole('link', { name: /My requests/ })).toHaveTextContent(
      '1 pending request',
    );
  });

  it('an admin:tokens-only persona opens /admin/tokens but not /admin/clients', async () => {
    fetchMyAccess.mockResolvedValue({ ...VIEWER, capabilities: ['chat:use', 'admin:tokens'] });
    renderAt('/admin/clients');
    expect(
      await screen.findByRole('region', { name: 'This area needs admin:clients' }),
    ).toBeInTheDocument();
    const side = screen.getByRole('complementary');
    const admin = within(side).getByRole('group', { name: 'Admin' });
    expect(
      within(admin)
        .getAllByRole('link')
        .map((l) => l.getAttribute('href')),
    ).toEqual(['/admin/tokens']);
  });

  it('a failed access answer renders the denied page, never the admin page', async () => {
    fetchMyAccess.mockRejectedValue(new Error('503'));
    renderAt('/admin/audit');
    expect(
      await screen.findByRole('region', { name: 'This area needs admin:audit' }),
    ).toHaveTextContent('Your role (unconfirmed)');
    expect(screen.queryByRole('heading', { level: 2, name: 'Audit' })).not.toBeInTheDocument();
  });

  it('an admin sees the Admin section with the approvals badge', async () => {
    renderAt('/account');
    const side = screen.getByRole('complementary');
    expect(await within(side).findByRole('group', { name: 'Admin' })).toBeInTheDocument();
    expect(within(side).getByRole('link', { name: /Access requests/ })).toHaveTextContent(
      '4 requests to decide',
    );
  });

  it('the command palette offers only the pages the viewer can open', async () => {
    fetchMyAccess.mockResolvedValue(VIEWER);
    renderAt('/account');
    await pageTitle('My access');
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    const palette = await screen.findByRole('dialog');
    expect(within(palette).getByRole('option', { name: 'My access' })).toBeInTheDocument();
    expect(within(palette).queryByRole('option', { name: 'Users' })).not.toBeInTheDocument();
  });
});
