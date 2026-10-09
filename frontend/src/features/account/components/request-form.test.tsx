import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { type CapabilityCatalog } from '@/api/access';
import { type AccessRequest, type RequestOptions } from '@/api/access-requests';
import { httpError } from '@/api/test-support';
import { type MyAccessView } from '@/api/hooks/use-my-access';
import { PERSONAS } from '@/test/access-view';
import { toast, Toaster } from '@/ui';
import { MyRequestsPage, NewRequestPage } from '../index';

// The account barrel reaches the token client, whose axios instance pulls in the Firebase SDK.
vi.mock('@/lib/firebase', () => ({ auth: {}, googleProvider: {} }));
const state = vi.hoisted(() => ({ view: null as unknown as MyAccessView }));
vi.mock('@/api/hooks/use-my-access', () => ({ useMyAccess: () => state.view }));
const fetchCapabilityCatalog = vi.hoisted(() => vi.fn<() => Promise<CapabilityCatalog>>());
vi.mock('@/api/access', () => ({ fetchCapabilityCatalog }));
const requests = vi.hoisted(() => ({
  fetchRequestOptions: vi.fn<(resource: string) => Promise<RequestOptions>>(),
  createRequest: vi.fn(),
  listMyRequests: vi.fn<() => Promise<AccessRequest[]>>(),
  cancelRequest: vi.fn(),
}));
vi.mock('@/api/access-requests', () => requests);

const RESOURCE = 'demo/checkout/checkout_funnel';
const OPTIONS: RequestOptions = {
  resource: RESOURCE,
  groups: [
    { id: 'g1', name: 'marketing-paid', managers: ['Sara Mansour', 'Omar Saleh'] },
    { id: 'g2', name: 'leadership', managers: [] },
  ],
  can_request_resource: true,
};
const CATALOG: CapabilityCatalog = {
  capabilities: [],
  roles: [
    { name: 'viewer', capabilities: ['chat:use'] },
    { name: 'analyst', capabilities: ['chat:use', 'mcp:use', 'tokens:create'] },
    { name: 'builder', capabilities: ['chat:use', 'mcp:use', 'tokens:create', 'atlas:build'] },
  ],
};
const SENT: AccessRequest = {
  id: 'r1',
  kind: 'group',
  target: 'g1',
  target_label: 'marketing-paid',
  note: 'Checkout drop-off review',
  status: 'pending',
  created_at: '2026-10-09T08:00:00Z',
  decided_by: null,
  decided_at: null,
  decision_note: '',
};

function renderAt(path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/account/requests/new" element={<NewRequestPage />} />
          <Route path="/account/requests" element={<MyRequestsPage />} />
        </Routes>
      </MemoryRouter>
      <Toaster />
    </QueryClientProvider>,
  );
}

const fromChat = `/account/requests/new?resource=${encodeURIComponent(RESOURCE)}&label=Checkout+funnel`;
const note = () => screen.getByRole('textbox', { name: /Why do you need it/ });
const send = () => userEvent.click(screen.getByRole('button', { name: 'Send request' }));

/** Sonner removes a toast on a timer; finish that before the environment is torn down. */
afterEach(async () => {
  toast.dismiss();
  await waitFor(() => expect(document.querySelector('[data-sonner-toast]')).toBeNull());
  cleanup();
});

describe('NewRequestPage / RequestForm', () => {
  beforeEach(() => {
    state.view = PERSONAS.newViewer;
    fetchCapabilityCatalog.mockReset().mockResolvedValue(CATALOG);
    requests.fetchRequestOptions.mockReset().mockResolvedValue(OPTIONS);
    requests.createRequest.mockReset().mockResolvedValue(SENT);
    requests.listMyRequests.mockReset().mockResolvedValue([]);
  });

  it('a chat denial prefills the resource kind and lists the groups that hold it', async () => {
    renderAt(fromChat);
    expect(screen.getByRole('radio', { name: 'Resource' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('textbox', { name: 'Resource' })).toHaveValue(RESOURCE);
    expect(screen.getByText(/Checkout funnel · prefilled from your chat/)).toBeInTheDocument();
    const list = await screen.findByRole('radiogroup', { name: 'Who can approve it' });
    expect(requests.fetchRequestOptions).toHaveBeenCalledWith(RESOURCE);
    expect(within(list).getByText('Decided by Sara Mansour or Omar Saleh')).toBeInTheDocument();
    expect(within(list).getByText('No managers · an admin decides')).toBeInTheDocument();
    expect(within(list).getByText('Direct grant for me only')).toBeInTheDocument();
    expect(list.textContent).not.toContain('@');
  });

  it('a prefilled path is read-only until Change, which drops the link label', async () => {
    renderAt(fromChat);
    const field = screen.getByRole('textbox', { name: 'Resource' });
    expect(field).toHaveAttribute('readonly');
    await userEvent.click(screen.getByRole('button', { name: 'Change' }));
    expect(field).not.toHaveAttribute('readonly');
    expect(screen.queryByText(/Checkout funnel/)).not.toBeInTheDocument();
    await userEvent.clear(field);
    await userEvent.type(field, 'demo/order{Enter}');
    await waitFor(() => expect(requests.fetchRequestOptions).toHaveBeenCalledWith('demo/order'));
    expect(screen.queryByText(/prefilled from your chat/)).not.toBeInTheDocument();
  });

  it('validates the choice and the note before sending, as the backend would', async () => {
    renderAt(fromChat);
    await screen.findByRole('radiogroup', { name: 'Who can approve it' });
    await send();
    expect(screen.getByText('Pick a group, or ask for a direct grant.')).toBeInTheDocument();
    expect(screen.getByText('Add a short note so an admin can decide.')).toBeInTheDocument();
    expect(note()).toHaveAttribute('aria-invalid', 'true');
    expect(requests.createRequest).not.toHaveBeenCalled();
  });

  it('picking a suggested group sends a group request, then it shows in My requests', async () => {
    requests.listMyRequests.mockResolvedValue([SENT]);
    renderAt(fromChat);
    await userEvent.click(await screen.findByRole('radio', { name: /marketing-paid/ }));
    expect(screen.getByText('Goes to Sara Mansour and Omar Saleh')).toBeInTheDocument();
    await userEvent.type(note(), 'Checkout drop-off review');
    await send();
    expect(requests.createRequest).toHaveBeenCalledWith({
      kind: 'group',
      target: 'g1',
      note: 'Checkout drop-off review',
    });
    expect(await screen.findByText('Sent to Sara Mansour and Omar Saleh.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('link', { name: /Track it in My requests/ }));
    expect(await screen.findByText('marketing-paid')).toBeInTheDocument();
    expect(screen.getByText('pending')).toBeInTheDocument();
  });

  it('a direct grant asks for the exact resource', async () => {
    renderAt(fromChat);
    await userEvent.click(await screen.findByRole('radio', { name: /Direct grant for me only/ }));
    await userEvent.type(note(), 'QA');
    await send();
    expect(requests.createRequest).toHaveBeenCalledWith({
      kind: 'resource',
      target: RESOURCE,
      note: 'QA',
    });
  });

  it('a resource the user already holds cannot be asked for directly', async () => {
    requests.fetchRequestOptions.mockResolvedValue({ ...OPTIONS, can_request_resource: false });
    renderAt(fromChat);
    const direct = await screen.findByRole('radio', { name: /Direct grant for me only/ });
    expect(direct).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText(/You already have access to/)).toBeInTheDocument();
  });

  it('the group kind finds groups by the data they hold', async () => {
    renderAt('/account/requests/new');
    expect(screen.getByRole('radio', { name: 'Group' })).toHaveAttribute('aria-checked', 'true');
    const field = screen.getByRole('textbox', { name: 'Data you need' });
    await userEvent.type(field, 'demo/*{Enter}');
    expect(
      screen.getByText('Enter one resource path like demo/order/revenue.'),
    ).toBeInTheDocument();
    expect(requests.fetchRequestOptions).not.toHaveBeenCalled();
    await userEvent.clear(field);
    await userEvent.type(field, 'demo/order{Enter}');
    expect(
      await screen.findByRole('radiogroup', { name: 'Groups that hold it' }),
    ).toBeInTheDocument();
    expect(requests.fetchRequestOptions).toHaveBeenCalledWith('demo/order');
    expect(screen.queryByText('Direct grant for me only')).not.toBeInTheDocument();
  });

  it('?kind=role offers only roles above the current one', async () => {
    renderAt('/account/requests/new?kind=role');
    const viewer = await screen.findByRole('radio', { name: /viewer/ });
    expect(viewer).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText('Your role today is')).toBeInTheDocument();
    const analyst = screen.getByRole('radio', { name: /analyst/ });
    expect(analyst).toHaveAttribute('aria-checked', 'true'); // the next role is preselected
    expect(within(analyst).getByText('mcp:use')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: /builder/ }));
    await userEvent.type(note(), 'Building dashboards');
    await send();
    expect(requests.createRequest).toHaveBeenCalledWith({
      kind: 'role',
      target: 'builder',
      note: 'Building dashboards',
    });
  });

  it("a backend 422 shows its sentence inline at the field it's about", async () => {
    requests.createRequest.mockRejectedValue(
      httpError(422, { detail: "You're already in marketing-paid." }),
    );
    renderAt(fromChat);
    await userEvent.click(await screen.findByRole('radio', { name: /marketing-paid/ }));
    await userEvent.type(note(), 'x');
    await send();
    expect(await screen.findByText("You're already in marketing-paid.")).toBeInTheDocument();
  });

  it('a duplicate (409) says so in an action toast that leads to My requests', async () => {
    requests.createRequest.mockRejectedValue(
      httpError(409, { detail: "You already asked for this; it's pending." }),
    );
    renderAt(fromChat);
    await userEvent.click(await screen.findByRole('radio', { name: /marketing-paid/ }));
    await userEvent.type(note(), 'x');
    await send();
    expect(await screen.findByText("You already asked for this; it's pending.")).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'View' }));
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 2, name: 'My requests' })).toBeInTheDocument(),
    );
  });
});
