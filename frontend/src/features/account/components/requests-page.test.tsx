import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { type AccessRequest } from '@/api/access-requests';
import { httpError } from '@/api/test-support';
import { toast, Toaster } from '@/ui';
import { MyRequestsPage } from './requests-page';

const requests = vi.hoisted(() => ({
  listMyRequests: vi.fn<() => Promise<AccessRequest[]>>(),
  cancelRequest: vi.fn<(id: string) => Promise<AccessRequest>>(),
}));
vi.mock('@/api/access-requests', () => requests);
vi.mock('@/api/access', () => ({ fetchMyAccess: vi.fn() }));

const PENDING: AccessRequest = {
  id: 'r1',
  kind: 'resource',
  target: 'demo/checkout/checkout_funnel',
  target_label: 'demo/checkout/checkout_funnel',
  note: 'Funnel review',
  status: 'pending',
  created_at: '2026-10-08T08:00:00Z',
  decided_by: null,
  decided_at: null,
  decision_note: '',
};
const DECLINED: AccessRequest = {
  ...PENDING,
  id: 'r2',
  kind: 'role',
  target: 'admin',
  target_label: 'admin',
  status: 'declined',
  decided_by: { user_id: 'u9', display_name: 'Sara Mansour' },
  decided_at: '2026-10-08T10:00:00Z',
  decision_note: 'Analyst covers this; ask for analyst instead.',
};
const CANCELLED: AccessRequest = {
  ...PENDING,
  status: 'cancelled',
  decided_at: PENDING.created_at,
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MyRequestsPage />
      </MemoryRouter>
      <Toaster />
    </QueryClientProvider>,
  );
}

/** Sonner removes a toast on a timer; finish that before the environment is torn down. */
afterEach(async () => {
  toast.dismiss();
  await waitFor(() => expect(document.querySelector('[data-sonner-toast]')).toBeNull());
  cleanup();
});

describe('MyRequestsPage', () => {
  beforeEach(() => {
    requests.listMyRequests.mockReset().mockResolvedValue([PENDING, DECLINED]);
    requests.cancelRequest.mockReset().mockResolvedValue(CANCELLED);
  });

  it('is empty with a way to ask', async () => {
    requests.listMyRequests.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Nothing requested yet' })).toBeVisible();
    expect(screen.getAllByRole('link', { name: /request/i }).length).toBeGreaterThan(0);
  });

  it('shows status pills, notes and the decision', async () => {
    renderPage();
    const declined = await screen.findByRole('article', { name: /admin/ });
    expect(within(declined).getByText('declined')).toBeInTheDocument();
    expect(within(declined).getByText('Sara Mansour')).toBeInTheDocument();
    expect(
      within(declined).getByText('Analyst covers this; ask for analyst instead.'),
    ).toBeInTheDocument();
    expect(within(declined).queryByRole('button')).not.toBeInTheDocument();
    const pending = screen.getByRole('article', { name: /checkout_funnel/ });
    expect(within(pending).getByText('pending')).toBeInTheDocument();
    expect(within(pending).getByText('“Funnel review”')).toBeInTheDocument();
  });

  it('cancelling is confirmed inline first, then the card shows it cancelled', async () => {
    renderPage();
    const pending = await screen.findByRole('article', { name: /checkout_funnel/ });
    await userEvent.click(within(pending).getByRole('button', { name: 'Cancel request' }));
    const review = within(pending).getByRole('region', { name: 'Cancel this request' });
    expect(review).toHaveTextContent('status pending');
    expect(review).toHaveTextContent('status cancelled');
    expect(requests.cancelRequest).not.toHaveBeenCalled();

    requests.listMyRequests.mockResolvedValue([CANCELLED, DECLINED]);
    await userEvent.click(within(review).getByRole('button', { name: 'Cancel request' }));
    expect(requests.cancelRequest).toHaveBeenCalledWith('r1');
    await waitFor(() => expect(within(pending).getByText('cancelled')).toBeInTheDocument());
    expect(within(pending).getByText('You cancelled it')).toBeInTheDocument();
  });

  it('a decision note shows even without a decider name', async () => {
    requests.listMyRequests.mockResolvedValue([
      { ...DECLINED, decided_by: { user_id: null, display_name: '' } },
    ]);
    renderPage();
    expect(
      await screen.findByText('Analyst covers this; ask for analyst instead.'),
    ).toBeInTheDocument();
  });

  it('Keep it dismisses the confirmation', async () => {
    renderPage();
    const pending = await screen.findByRole('article', { name: /checkout_funnel/ });
    await userEvent.click(within(pending).getByRole('button', { name: 'Cancel request' }));
    await userEvent.click(within(pending).getByRole('button', { name: 'Dismiss' }));
    expect(within(pending).queryByRole('region')).not.toBeInTheDocument();
  });

  it('an already-decided request (409) says so in an action toast and reloads', async () => {
    requests.cancelRequest.mockRejectedValue(
      httpError(409, { detail: 'This request was already decided.' }),
    );
    renderPage();
    const pending = await screen.findByRole('article', { name: /checkout_funnel/ });
    await userEvent.click(within(pending).getByRole('button', { name: 'Cancel request' }));
    const review = within(pending).getByRole('region', { name: 'Cancel this request' });
    await userEvent.click(within(review).getByRole('button', { name: 'Cancel request' }));
    expect(await screen.findByText('This request was already decided.')).toBeVisible();
    const before = requests.listMyRequests.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    await waitFor(() => expect(requests.listMyRequests.mock.calls.length).toBeGreaterThan(before));
  });

  it('a failed load states the fact with a retry', async () => {
    requests.listMyRequests.mockRejectedValue(httpError(503));
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't load your requests");
    requests.listMyRequests.mockResolvedValue([PENDING]);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('article', { name: /checkout_funnel/ })).toBeInTheDocument();
  });
});
