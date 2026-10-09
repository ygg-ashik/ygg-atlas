// Route smoke test: every account and admin route resolves through its guard.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type MeAccess } from '@/api/access';
import { ThemeProvider } from '@/lib/theme-provider';
import { AppRoutes } from './App';

const fetchMyAccess = vi.hoisted(() => vi.fn<() => Promise<MeAccess>>());
vi.mock('@/api/access', () => ({ fetchMyAccess }));
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
};
const ADMIN: MeAccess = {
  ...VIEWER,
  role: 'admin',
  capabilities: ['chat:use', 'admin:users', 'admin:groups', 'admin:audit'],
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
    ['/account/requests/new?kind=role', 'New request'],
    ['/account/tokens', 'Tokens & connected apps'],
    ['/admin/users', 'Users'],
    ['/admin/users/u-9', 'User'],
    ['/admin/groups', 'Groups'],
    ['/admin/groups/g-1', 'Group'],
    ['/admin/requests', 'Access requests'],
    ['/admin/audit', 'Audit'],
  ])('%s renders its page for an admin', async (path, title) => {
    renderAt(path);
    expect(await pageTitle(title)).toBeInTheDocument();
    expect(document.querySelector('[data-route-label]')).toHaveTextContent(path.split('?')[0]!);
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
