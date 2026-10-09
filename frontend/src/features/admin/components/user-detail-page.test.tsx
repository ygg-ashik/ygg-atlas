import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { apiMock } from '@/api/test-api-mock';
import { httpError } from '@/api/test-support';
import { PERSONAS } from '@/test/access-view';
import { CATALOG, detail, diffLines, fast, grant } from './test-fixtures';
import { UserDetailPage } from './user-detail-page';

vi.mock('../hooks/use-debounced-value', () => ({ useDebouncedValue: <T,>(value: T) => value }));
vi.mock('@/api/axios-instance', () => apiMock);
const fetchUserDetail = vi.hoisted(() => vi.fn());
vi.mock('@/api/admin-users', () => ({ fetchUserDetail, fetchEffectiveAccess: vi.fn() }));
vi.mock('@/api/access', () => ({ fetchCapabilityCatalog: () => Promise.resolve(CATALOG) }));
vi.mock('@/api/hooks/use-my-access', () => ({ useMyAccess: () => PERSONAS.admin }));
const listAdminTokens = vi.hoisted(() => vi.fn());
const revokeAllUserTokens = vi.hoisted(() => vi.fn());
vi.mock('@/api/tokens', () => ({ listAdminTokens, revokeAllUserTokens }));
const listDecidableRequests = vi.hoisted(() => vi.fn());
vi.mock('@/api/access-requests', () => ({ listDecidableRequests }));

const TOKEN = {
  id: 't1',
  kind: 'pat',
  name: 'Claude Code · laptop',
  prefix: 'atl_pat_77c1',
  user_id: 'karim',
  client_id: null,
  created_at: '2026-10-01T00:00:00Z',
  expires_at: '2026-12-30T00:00:00Z',
  last_used_at: null,
  revoked_at: null,
  revoked_reason: null,
};

function renderAt(path: string) {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/admin/users/:id" element={<UserDetailPage />} />
        </Routes>
      </MemoryRouter>
    </Wrapper>,
  );
}

describe('UserDetailPage', () => {
  beforeEach(() => {
    fetchUserDetail.mockReset();
    fetchUserDetail.mockImplementation((id: string) =>
      Promise.resolve(
        detail(id, {
          display_name: id === 'u1' ? 'Ashik Babu' : 'Karim Nasser',
          groups: [{ id: 'g-m', name: 'marketing', standing: 'member' }],
          direct_grants: [
            grant('c61d77', {
              subject_type: 'user',
              target: 'demo/checkout/checkout_funnel',
              reason: 'Funnel QA',
            }),
          ],
        }),
      ),
    );
    listAdminTokens.mockReset();
    revokeAllUserTokens.mockReset();
    listDecidableRequests.mockReset();
  });

  it('titles the page with the user and a Users breadcrumb back to the list', async () => {
    renderAt('/admin/users/karim');
    expect(await screen.findByRole('heading', { level: 1, name: 'Karim Nasser' })).toBeVisible();
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(within(crumbs).getByRole('link', { name: 'Users' })).toHaveAttribute(
      'href',
      '/admin/users',
    );
  });

  it('shows the user with their groups', async () => {
    renderAt('/admin/users/karim');
    expect(
      await screen.findByRole('heading', { level: 2, name: 'Karim Nasser' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open marketing' })).toHaveAttribute(
      'href',
      '/admin/groups/g-m',
    );
  });

  it('on yourself, role, status and grants are locked with the backend sentences', async () => {
    renderAt('/admin/users/u1');
    expect(await screen.findByRole('combobox', { name: 'Role' })).toBeDisabled();
    await fast().click(screen.getByRole('tab', { name: /Direct grants/ }));
    expect(screen.getByRole('button', { name: '＋ Add grant' })).toBeDisabled();
    expect(
      screen.getByText("You can't grant access to yourself. Ask another admin."),
    ).toBeInTheDocument();
  });

  it('a direct grant revoke is reviewed first', async () => {
    renderAt('/admin/users/karim?tab=grants');
    await fast().click(
      await screen.findByRole('button', { name: 'Revoke allow demo/checkout/checkout_funnel' }),
    );
    const card = screen.getByRole('region', { name: 'Revoke grant' });
    expect(diffLines(card)[0]).toEqual(['context', 'grant.revoke  user:karim@']);
  });

  it('tokens tab: not available until phase 4', async () => {
    listAdminTokens.mockResolvedValue({ available: false, reason: 'missing' });
    renderAt('/admin/users/karim?tab=tokens');
    expect(await screen.findByText('Not available yet')).toBeInTheDocument();
  });

  it('tokens tab: revoke all goes through a review card', async () => {
    listAdminTokens.mockResolvedValue({ available: true, data: [TOKEN] });
    revokeAllUserTokens.mockResolvedValue({ revoked: 1 });
    renderAt('/admin/users/karim?tab=tokens');
    await fast().click(await screen.findByRole('button', { name: 'Revoke all' }));
    const card = screen.getByRole('region', { name: 'Revoke all tokens · Karim Nasser' });
    expect(diffLines(card)).toContainEqual([
      'remove',
      'token     atl_pat_77c1…  Claude Code · laptop',
    ]);
    expect(revokeAllUserTokens).not.toHaveBeenCalled();
    await fast().click(within(card).getByRole('button', { name: 'Revoke 1 tokens' }));
    expect(revokeAllUserTokens).toHaveBeenCalledWith('karim');
    await waitFor(() => expect(card).toHaveAttribute('data-status', 'applied'));
  });

  it('tokens tab: a missing revoke-all route reads not available', async () => {
    listAdminTokens.mockResolvedValue({ available: true, data: [TOKEN] });
    revokeAllUserTokens.mockRejectedValue(httpError(404, { detail: 'Not Found' }));
    renderAt('/admin/users/karim?tab=tokens');
    await fast().click(await screen.findByRole('button', { name: 'Revoke all' }));
    await fast().click(screen.getByRole('button', { name: 'Revoke 1 tokens' }));
    expect(await screen.findByText('Not available yet')).toBeInTheDocument();
  });

  it('a missing user is stated with Retry', async () => {
    fetchUserDetail.mockRejectedValue(httpError(404, { detail: 'No such user.' }));
    renderAt('/admin/users/nope');
    expect(await screen.findByText("Couldn't load this user")).toBeInTheDocument();
  });

  it("requests tab: lists this user's requests from the scoped queue", async () => {
    listDecidableRequests.mockResolvedValue({
      items: [
        {
          id: 'r1',
          kind: 'resource',
          target: 'demo/checkout/checkout_funnel',
          target_label: 'demo/checkout/checkout_funnel',
          note: 'Funnel QA',
          status: 'declined',
          created_at: '2026-10-08T11:00:00Z',
          decided_by: null,
          decided_at: null,
          decision_note: '',
        },
      ],
      next_cursor: null,
    });
    renderAt('/admin/users/karim?tab=requests');
    const list = await screen.findByRole('list', { name: 'Requests from Karim Nasser' });
    const item = within(list).getByRole('listitem');
    expect(within(item).getByText('demo/checkout/checkout_funnel')).toHaveClass('font-mono');
    expect(within(item).getByText('declined')).toBeInTheDocument();
    expect(listDecidableRequests).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'all', user_id: 'karim' }),
    );
  });

  it('requests tab: none in scope reads as an empty state', async () => {
    listDecidableRequests.mockResolvedValue({ items: [], next_cursor: null });
    renderAt('/admin/users/karim?tab=requests');
    expect(await screen.findByText('No requests')).toBeInTheDocument();
  });

  it('requests tab: a viewer who decides nothing reads the backend sentence', async () => {
    listDecidableRequests.mockRejectedValue(
      httpError(403, { detail: 'You have no access requests to decide.' }),
    );
    renderAt('/admin/users/karim?tab=requests');
    expect(await screen.findByText('Not in your queue')).toBeInTheDocument();
    expect(screen.getByText(/You have no access requests to decide\./)).toBeInTheDocument();
  });
});
