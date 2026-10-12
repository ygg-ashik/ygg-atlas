// ⌘K quick actions: each runs in place over the page, through the features' own
// dialogs, and only for the capabilities `/me/access` reports.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { type MeAccess } from '@/api/access';
import { type AccessRequest } from '@/api/access-requests';
import { useMyAccess } from '@/api/hooks/use-my-access';
import { type Token } from '@/api/tokens';
import { ThemeProvider } from '@/lib/theme-provider';
import { Toaster } from '@/ui';
import { CommandPalette } from '@/features/command';
import { useQuickActions } from './quick-actions';

const { http } = vi.hoisted(() => ({
  http: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock('@/api/axios-instance', () => ({ api: http, backendUrl: '' }));
vi.mock('@/lib/firebase', () => ({ auth: {}, googleProvider: {} }));

const VIEWER: MeAccess = {
  role: 'viewer',
  capabilities: ['chat:use'],
  groups: [{ id: 'g1', name: 'marketing', standing: 'member' }],
  has_data_access: true,
  user_id: 'u1',
  email: 'omar@yougotagift.com',
  display_name: 'Omar Saleh',
  pending_requests: 0,
  pending_approvals: 0,
  is_manager: false,
  clearances: [],
};
const ANALYST: MeAccess = {
  ...VIEWER,
  role: 'analyst',
  capabilities: ['chat:use', 'mcp:use', 'tokens:create'],
};
const MANAGER: MeAccess = { ...ANALYST, is_manager: true, pending_approvals: 1 };
const ADMIN: MeAccess = {
  ...VIEWER,
  role: 'admin',
  capabilities: ['chat:use', 'admin:users', 'admin:groups', 'admin:tokens'],
  pending_approvals: 2,
};

const REQUEST: AccessRequest = {
  id: 'r-1',
  kind: 'group',
  target: 'marketing-paid',
  target_label: 'marketing-paid',
  note: 'Running paid social for Q4.',
  status: 'pending',
  created_at: '2026-10-09T08:00:00Z',
  decided_by: null,
  decided_at: null,
  decision_note: '',
  requester: {
    user_id: 'u9',
    email: 'dana@yougotagift.com',
    display_name: 'Dana Q',
    role: 'viewer',
  },
};
const OWN: AccessRequest = {
  ...REQUEST,
  id: 'r-own',
  requester: { ...REQUEST.requester!, user_id: 'u1' },
};
const TOKEN: Token = {
  id: 't-1',
  kind: 'pat',
  name: 'ci runner',
  prefix: 'atl_pat_ab12',
  user_id: 'karim@yougotagift.com',
  client_id: null,
  created_at: '2026-10-01T00:00:00Z',
  expires_at: '2027-01-01T00:00:00Z',
  last_used_at: null,
  revoked_at: null,
  revoked_reason: null,
};

let me: MeAccess = VIEWER;
function answer() {
  http.get.mockImplementation((url: string) => {
    const data: Record<string, unknown> = {
      '/me/access': me,
      '/meta/auth-methods': {
        pat: { enabled: true, default_days: 90, max_days: 365 },
        oauth: { enabled: false, hosted_connectors: false },
      },
      '/meta/capabilities': {
        capabilities: [],
        roles: [],
        clearances: [],
        label_classes: [],
        mask_modes: [],
      },
      '/admin/requests': { items: [OWN, REQUEST], next_cursor: null },
      '/admin/tokens': [TOKEN],
    };
    return url in data ? Promise.resolve({ data: data[url] }) : new Promise(() => {});
  });
  http.post.mockResolvedValue({ data: { ...REQUEST, status: 'approved' } });
  http.delete.mockResolvedValue({ data: {} });
}

let path = '';
function Harness() {
  const view = useMyAccess();
  const [open, setOpen] = useState(false);
  const quick = useQuickActions(view, open);
  const l = useLocation();
  path = l.pathname;
  return (
    <>
      <p>{view.status}</p>
      <CommandPalette pages={[]} actions={quick.actions} onOpenChange={setOpen} />
      {quick.host}
    </>
  );
}

async function renderPalette(access: MeAccess) {
  me = access;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <MemoryRouter initialEntries={['/ask']}>
          <Routes>
            <Route path="*" element={<Harness />} />
          </Routes>
        </MemoryRouter>
        <Toaster />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  await screen.findByText('ready');
  fireEvent.keyDown(window, { key: 'k', metaKey: true });
  return screen.findByRole('dialog', { name: 'Command palette' });
}

const actionNames = (palette: HTMLElement) => {
  const group = within(palette).queryByRole('group', { name: 'Quick actions' });
  return group
    ? within(group)
        .getAllByRole('option')
        .map((o) => o.textContent ?? '')
    : [];
};

beforeEach(answer);
afterEach(() => {
  vi.clearAllMocks();
  localStorage.removeItem('ygg-atlas-theme');
});

describe('Quick actions', () => {
  it('a viewer gets theme, Request access and My access, nothing gated', async () => {
    const palette = await renderPalette(VIEWER);
    const names = actionNames(palette);
    expect(names.some((n) => n.startsWith('Theme: Dark'))).toBe(true);
    expect(names.some((n) => n.startsWith('Theme: System'))).toBe(false); // once you type
    expect(names.some((n) => n.startsWith('Request access'))).toBe(true);
    expect(names.some((n) => n.startsWith('My access'))).toBe(true);
    expect(names.some((n) => /New token|Approve|Revoke/.test(n))).toBe(false);
    expect(http.get).not.toHaveBeenCalledWith('/admin/requests', expect.anything());
    expect(http.get).not.toHaveBeenCalledWith('/admin/tokens', expect.anything());
  });

  it('theme switches instantly and confirms with a toast', async () => {
    const palette = await renderPalette(VIEWER);
    await userEvent.click(within(palette).getByRole('option', { name: /Theme: Dark/ }));
    expect(document.documentElement).toHaveClass('dark');
    expect(await screen.findByText('Theme: Dark')).toBeInTheDocument();
  });

  it('New token opens the token dialog, with tokens:create only', async () => {
    const palette = await renderPalette(ANALYST);
    await userEvent.click(await within(palette).findByRole('option', { name: /New token/ }));
    expect(await screen.findByRole('dialog', { name: 'New personal token' })).toBeInTheDocument();
    expect(path).toBe('/ask');
  });

  it('Request access opens the request form as a dialog', async () => {
    const palette = await renderPalette(VIEWER);
    await userEvent.click(within(palette).getByRole('option', { name: /Request access/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Request access' });
    expect(within(dialog).getByRole('form', { name: 'Access request' })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('My access peeks at role and groups, with one way to the full page', async () => {
    const palette = await renderPalette(VIEWER);
    await userEvent.click(within(palette).getByRole('option', { name: /My access/ }));
    const peek = await screen.findByRole('dialog', { name: 'My access' });
    expect(peek).toHaveTextContent('Omar Saleh');
    expect(peek).toHaveTextContent('viewer');
    expect(within(peek).getByRole('list', { name: 'Groups' })).toHaveTextContent('marketing');
    expect(within(peek).getByText('chat:use')).toBeInTheDocument();
    await userEvent.click(within(peek).getByRole('link', { name: 'Open full page →' }));
    expect(path).toBe('/settings/access');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it("a manager approves someone else's request through its review card", async () => {
    const palette = await renderPalette(MANAGER);
    const option = await within(palette).findByRole('option', { name: /Approve request · Dana Q/ });
    expect(option).toHaveTextContent('manager');
    expect(actionNames(palette).filter((n) => n.startsWith('Approve'))).toHaveLength(1);
    await userEvent.click(option);
    const dialog = await screen.findByRole('dialog', { name: 'Approve request' });
    expect(within(dialog).getByText('Running paid social for Q4.', { exact: false })).toBeVisible();
    await userEvent.click(within(dialog).getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(http.post).toHaveBeenCalledWith('/admin/requests/r-1/approve', {}));
  });

  it('Dismiss on the review card closes the approval dialog', async () => {
    const palette = await renderPalette(MANAGER);
    await userEvent.click(await within(palette).findByRole('option', { name: /Approve request/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Approve request' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(http.post).not.toHaveBeenCalled();
  });

  it('an admin:tokens holder revokes a token through its review card', async () => {
    const palette = await renderPalette(ADMIN);
    const option = await within(palette).findByRole('option', {
      name: /Revoke token atl_pat_ab12/,
    });
    expect(option).toHaveTextContent('admin');
    await userEvent.click(option);
    const dialog = await screen.findByRole('dialog', { name: /Revoke atl_pat_ab12/ });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Revoke token' }));
    await waitFor(() => expect(http.delete).toHaveBeenCalledWith('/admin/tokens/t-1'));
  });

  it('an analyst without admin capabilities is never offered approvals or revokes', async () => {
    const palette = await renderPalette(ANALYST);
    await within(palette).findByRole('option', { name: /New token/ });
    await userEvent.type(within(palette).getByRole('combobox'), 'revoke');
    expect(within(palette).queryByRole('option', { name: /Revoke/ })).toBeNull();
    expect(http.get).not.toHaveBeenCalledWith('/admin/tokens', expect.anything());
  });
});
