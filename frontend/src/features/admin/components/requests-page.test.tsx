import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type MeAccess } from '@/api/access';
import { type AccessRequest } from '@/api/access-requests';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { httpError } from '@/api/test-support';
import { plusDays, todayUtc } from '../grant-rules';
import { CATALOG, diffLines, fast } from './test-fixtures';
import { AdminRequestsPage } from './requests-page';

const listDecidableRequests = vi.hoisted(() => vi.fn());
const approveRequest = vi.hoisted(() => vi.fn());
const declineRequest = vi.hoisted(() => vi.fn());
vi.mock('@/api/access-requests', () => ({
  listDecidableRequests,
  approveRequest,
  declineRequest,
}));
const fetchMyAccess = vi.hoisted(() => vi.fn<() => Promise<MeAccess>>());
vi.mock('@/api/access', () => ({
  fetchMyAccess,
  fetchCapabilityCatalog: () => Promise.resolve(CATALOG),
}));

const ME: MeAccess = {
  role: 'admin',
  capabilities: ['chat:use', 'admin:users', 'admin:groups', 'admin:audit'],
  groups: [],
  has_data_access: true,
  user_id: 'u1',
  email: 'ashik@yougotagift.com',
  display_name: 'Ashik Babu',
  pending_requests: 0,
  pending_approvals: 3,
  is_manager: false,
};

function req(id: string, overrides: Partial<AccessRequest> = {}): AccessRequest {
  return {
    id,
    kind: 'group',
    target: 'g-m',
    target_label: 'marketing',
    note: 'Joining the growth team.',
    status: 'pending',
    created_at: '2026-10-09T09:46:00Z',
    decided_by: null,
    decided_at: null,
    decision_note: '',
    requester: {
      user_id: 'omar',
      email: 'omar@yougotagift.com',
      display_name: 'Omar Khalil',
      role: 'viewer',
    },
    ...overrides,
  };
}

const GROUP = req('r-group');
const ROLE = req('r-role', {
  kind: 'role',
  target: 'builder',
  target_label: 'builder',
  created_at: '2026-10-08T17:30:00Z',
  requester: {
    user_id: 'karim',
    email: 'karim@yougotagift.com',
    display_name: 'Karim Nasser',
    role: 'analyst',
  },
});
const RESOURCE = req('r-res', {
  kind: 'resource',
  target: 'demo/checkout/checkout_funnel',
  target_label: 'demo/checkout/checkout_funnel',
  created_at: '2026-10-08T11:00:00Z',
  requester: {
    user_id: 'sara',
    email: 'sara@yougotagift.com',
    display_name: 'Sara Mansour',
    role: 'viewer',
  },
});

let pending: AccessRequest[] = [];
let decided: AccessRequest[] = [];

function renderPage() {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <MemoryRouter initialEntries={['/admin/requests']}>
        <AdminRequestsPage />
      </MemoryRouter>
    </Wrapper>,
  );
}

const card = (name: string) => screen.getByRole('article', { name: new RegExp(name) });
const pendingTab = () => screen.getByRole('tab', { name: /Pending/ });

async function openApprove(name: string) {
  await fast().click(
    within(await screen.findByRole('article', { name: new RegExp(name) })).getByRole('button', {
      name: 'Approve',
    }),
  );
  return screen.getByRole('region', { name: /Approve request/ });
}

describe('AdminRequestsPage', () => {
  beforeEach(() => {
    pending = [GROUP, ROLE, RESOURCE];
    decided = [];
    listDecidableRequests.mockReset();
    listDecidableRequests.mockImplementation(({ status }: { status: string }) =>
      Promise.resolve({ items: status === 'pending' ? pending : decided, next_cursor: null }),
    );
    approveRequest.mockReset();
    declineRequest.mockReset();
    fetchMyAccess.mockReset().mockResolvedValue(ME);
  });

  it('lists pending cards with requester, kind, mono target and note', async () => {
    renderPage();
    const group = await screen.findByRole('article', { name: /Omar Khalil/ });
    expect(within(group).getByText('09 Oct 09:46')).toBeInTheDocument();
    expect(within(group).getByText('omar@yougotagift.com')).toBeInTheDocument();
    expect(within(group).getByText('group')).toBeInTheDocument();
    expect(within(group).getByText('marketing')).toHaveClass('font-mono');
    expect(within(group).getByText('“Joining the growth team.”')).toBeInTheDocument();
    expect(within(card('Karim Nasser')).getByText('analyst → builder')).toHaveClass('font-mono');
    expect(listDecidableRequests).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'pending' }),
    );
  });

  it('the Pending count is the sidebar badge set (pending_approvals)', async () => {
    renderPage();
    await waitFor(() => expect(pendingTab()).toHaveTextContent('3'));
  });

  it('approving a group request reviews the exact membership, with no expiry', async () => {
    approveRequest.mockResolvedValue({ ...GROUP, status: 'approved' });
    renderPage();
    const review = await openApprove('Omar Khalil');
    expect(diffLines(review)).toContainEqual(['add', 'member omar@yougotagift.com in marketing']);
    expect(within(review).queryByLabelText(/Expiry/)).not.toBeInTheDocument();
    expect(within(review).getByText('request.approve + member.put')).toBeInTheDocument();
    await fast().click(within(review).getByRole('button', { name: 'Approve' }));
    expect(approveRequest).toHaveBeenCalledWith('r-group', {});
  });

  it('approving a role request reviews the role change', async () => {
    approveRequest.mockResolvedValue({ ...ROLE, status: 'approved' });
    renderPage();
    const review = await openApprove('Karim Nasser');
    expect(diffLines(review)).toContainEqual(['add', 'role analyst → builder']);
    expect(diffLines(review)).toContainEqual(['context', 'gains     artifacts:save']);
    expect(within(review).getByText('request.approve + user.role')).toBeInTheDocument();
    expect(within(review).queryByLabelText(/Expiry/)).not.toBeInTheDocument();
  });

  it('a resource approval prefills +90 days; clearing sends null (no expiry)', async () => {
    approveRequest.mockResolvedValue({ ...RESOURCE, status: 'approved' });
    renderPage();
    const review = await openApprove('Sara Mansour');
    const date = plusDays(todayUtc(), 90);
    expect(within(review).getByText('request.approve + grant.create')).toBeInTheDocument();
    const expiry = within(review).getByLabelText(/Expiry/);
    expect(expiry).toHaveValue(date);
    expect(diffLines(review)).toContainEqual([
      'add',
      `grant allow demo/checkout/checkout_funnel for sara@yougotagift.com until ${date}`,
    ]);
    await fast().click(within(review).getByRole('button', { name: 'No expiry' }));
    expect(expiry).toHaveValue('');
    expect(diffLines(review)).toContainEqual([
      'add',
      'grant allow demo/checkout/checkout_funnel for sara@yougotagift.com, no expiry',
    ]);
    await fast().click(within(review).getByRole('button', { name: 'Approve' }));
    expect(approveRequest).toHaveBeenCalledWith('r-res', { expires_at: null });
  });

  it('a resource approval sends the reviewed expiry date', async () => {
    approveRequest.mockResolvedValue({ ...RESOURCE, status: 'approved' });
    renderPage();
    const review = await openApprove('Sara Mansour');
    await fast().click(within(review).getByRole('button', { name: 'Approve' }));
    const date = plusDays(todayUtc(), 90);
    expect(approveRequest).toHaveBeenCalledWith('r-res', { expires_at: `${date}T00:00:00Z` });
  });

  it('decline needs no note', async () => {
    declineRequest.mockResolvedValue({ ...GROUP, status: 'declined' });
    renderPage();
    await fast().click(
      within(await screen.findByRole('article', { name: /Omar Khalil/ })).getByRole('button', {
        name: 'Decline',
      }),
    );
    await fast().click(screen.getByRole('button', { name: 'Decline request' }));
    expect(declineRequest).toHaveBeenCalledWith('r-group', {});
  });

  it('decline sends the optional note', async () => {
    declineRequest.mockResolvedValue({ ...GROUP, status: 'declined' });
    renderPage();
    await fast().click(
      within(await screen.findByRole('article', { name: /Omar Khalil/ })).getByRole('button', {
        name: 'Decline',
      }),
    );
    await fast().type(screen.getByRole('textbox', { name: /Note to Omar/ }), 'Not this quarter.');
    await fast().click(screen.getByRole('button', { name: 'Decline request' }));
    expect(declineRequest).toHaveBeenCalledWith('r-group', { note: 'Not this quarter.' });
  });

  it('your own request shows no actions', async () => {
    pending = [
      req('r-own', {
        requester: { ...GROUP.requester!, user_id: 'u1', display_name: 'Ashik Babu' },
      }),
    ];
    renderPage();
    const own = await screen.findByRole('article', { name: /Ashik Babu/ });
    expect(within(own).queryByRole('button')).not.toBeInTheDocument();
    expect(within(own).getByText('your request')).toBeInTheDocument();
  });

  it('a 409 after someone else decided refreshes the row and offers no Retry', async () => {
    approveRequest.mockRejectedValue(
      httpError(409, { detail: 'This request was already decided.' }),
    );
    renderPage();
    const review = await openApprove('Omar Khalil');
    pending = [ROLE, RESOURCE];
    await fast().click(within(review).getByRole('button', { name: 'Approve' }));
    const row = card('Omar Khalil');
    expect(await within(row).findByText('This request was already decided.')).toBeInTheDocument();
    expect(
      within(row).queryByRole('button', { name: /Retry|Approve|Decline/ }),
    ).not.toBeInTheDocument();
    expect(listDecidableRequests.mock.calls.length).toBeGreaterThan(1);
  });

  it('a stale-actor 409 on a still-pending row offers Retry', async () => {
    approveRequest.mockRejectedValueOnce(
      httpError(409, { detail: 'Access changed while this request was running; retry.' }),
    );
    renderPage();
    const review = await openApprove('Omar Khalil');
    await fast().click(within(review).getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(review).toHaveAttribute('data-status', 'conflict'));
    approveRequest.mockResolvedValue({ ...GROUP, status: 'approved' });
    await fast().click(within(review).getByRole('button', { name: /Retry/ }));
    expect(approveRequest).toHaveBeenCalledTimes(2);
  });

  it('the Pending count decrements after a decision', async () => {
    approveRequest.mockResolvedValue({
      ...GROUP,
      status: 'approved',
      decided_by: { user_id: 'u1', display_name: 'Ashik Babu' },
    });
    renderPage();
    await waitFor(() => expect(pendingTab()).toHaveTextContent('3'));
    const review = await openApprove('Omar Khalil');
    fetchMyAccess.mockResolvedValue({ ...ME, pending_approvals: 2 });
    pending = [ROLE, RESOURCE];
    await fast().click(within(review).getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(pendingTab()).toHaveTextContent('2'));
    expect(within(card('Omar Khalil')).getByText('approved')).toBeInTheDocument();
  });

  it('Decided lists finished requests with the decider and note', async () => {
    decided = [
      req('r-done', {
        status: 'declined',
        decided_by: { user_id: 'y', display_name: 'Yousef Darwish' },
        decided_at: '2026-10-02T10:00:00Z',
        decision_note: 'Paid search moved to the agency.',
      }),
    ];
    renderPage();
    await screen.findByRole('article', { name: /Omar Khalil/ });
    await fast().click(screen.getByRole('tab', { name: /Decided/ }));
    const done = await screen.findByRole('article', { name: /Omar Khalil/ });
    expect(within(done).getByText('declined')).toBeInTheDocument();
    expect(within(done).getByText(/Yousef Darwish/)).toBeInTheDocument();
    expect(within(done).getByText(/Paid search moved to the agency\./)).toBeInTheDocument();
    expect(within(done).queryByRole('button')).not.toBeInTheDocument();
    expect(listDecidableRequests).toHaveBeenCalledWith(expect.objectContaining({ status: 'all' }));
  });

  it('a manager reads that only their subtree group requests are here', async () => {
    fetchMyAccess.mockResolvedValue({
      ...ME,
      role: 'analyst',
      capabilities: ['chat:use'],
      is_manager: true,
    });
    pending = [GROUP];
    renderPage();
    expect(await screen.findByText(/Group requests for the groups you manage/)).toBeInTheDocument();
  });

  it('an empty queue says you are caught up', async () => {
    pending = [];
    renderPage();
    expect(await screen.findByText('No pending requests')).toBeInTheDocument();
  });

  it('an invalid expiry blocks the approval and says what to do', async () => {
    renderPage();
    const review = await openApprove('Sara Mansour');
    const expiry = within(review).getByLabelText(/Expiry/);
    await fast().clear(expiry);
    await fast().type(expiry, '2026-13-40');
    await fast().click(within(review).getByRole('button', { name: 'Approve' }));
    expect(within(review).getByText(/Enter a date as YYYY-MM-DD/)).toBeInTheDocument();
    expect(approveRequest).not.toHaveBeenCalled();
  });

  it('a declined request shows its outcome in place', async () => {
    declineRequest.mockResolvedValue({
      ...GROUP,
      status: 'declined',
      decided_by: { user_id: 'u1', display_name: 'Ashik Babu' },
      decided_at: '2026-10-09T10:00:00Z',
      decision_note: 'Not this quarter.',
    });
    renderPage();
    await fast().click(
      within(await screen.findByRole('article', { name: /Omar Khalil/ })).getByRole('button', {
        name: 'Decline',
      }),
    );
    pending = [ROLE, RESOURCE];
    await fast().click(screen.getByRole('button', { name: 'Decline request' }));
    const row = card('Omar Khalil');
    expect(await within(row).findByText('declined')).toBeInTheDocument();
    expect(within(row).getByText(/Not this quarter\./)).toBeInTheDocument();
    expect(within(row).queryByRole('button')).not.toBeInTheDocument();
  });

  it('a decline 409 after someone else decided refreshes the row', async () => {
    declineRequest.mockRejectedValue(
      httpError(409, { detail: 'This request was already decided.' }),
    );
    renderPage();
    await fast().click(
      within(await screen.findByRole('article', { name: /Omar Khalil/ })).getByRole('button', {
        name: 'Decline',
      }),
    );
    pending = [ROLE, RESOURCE];
    await fast().click(screen.getByRole('button', { name: 'Decline request' }));
    const row = card('Omar Khalil');
    expect(await within(row).findByText('This request was already decided.')).toBeInTheDocument();
    expect(within(row).queryByRole('button')).not.toBeInTheDocument();
  });

  it('Keep pending closes the decline panel without writing', async () => {
    renderPage();
    const row = await screen.findByRole('article', { name: /Omar Khalil/ });
    await fast().click(within(row).getByRole('button', { name: 'Decline' }));
    await fast().click(within(row).getByRole('button', { name: 'Keep pending' }));
    expect(within(row).getByRole('button', { name: 'Approve' })).toBeInTheDocument();
    expect(declineRequest).not.toHaveBeenCalled();
  });

  it('shows a skeleton while the queue loads', () => {
    listDecidableRequests.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole('status')).toHaveTextContent('Loading access requests');
  });

  it('a load failure is stated with a Retry', async () => {
    listDecidableRequests.mockRejectedValueOnce(httpError(503));
    renderPage();
    expect(await screen.findByText("Couldn't load access requests")).toBeInTheDocument();
    await fast().click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('article', { name: /Omar Khalil/ })).toBeInTheDocument();
  });

  it('follows next_cursor with Load more', async () => {
    listDecidableRequests.mockImplementation(({ cursor }: { cursor?: string }) =>
      Promise.resolve(
        cursor ? { items: [ROLE], next_cursor: null } : { items: [GROUP], next_cursor: 'c1' },
      ),
    );
    renderPage();
    await screen.findByRole('article', { name: /Omar Khalil/ });
    await fast().click(screen.getByRole('button', { name: 'Load more' }));
    expect(await screen.findByRole('article', { name: /Karim Nasser/ })).toBeInTheDocument();
  });
});
