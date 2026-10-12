import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { type OAuthClient } from '@/api/tokens';
import { fast } from './test-fixtures';
import { AdminClientsPage } from './clients-page';

const tokens = vi.hoisted(() => ({
  listClients: vi.fn<() => Promise<OAuthClient[]>>(),
  revokeClient: vi.fn<(id: string) => Promise<void>>(),
}));
// The real token client is spread in; its axios instance pulls in the Firebase SDK.
vi.mock('@/lib/firebase', () => ({ auth: {}, googleProvider: {} }));
vi.mock('@/api/tokens', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ...tokens,
}));

const CLIENT: OAuthClient = {
  client_id: 'oc_8f3a1c',
  client_name: 'Claude Code',
  redirect_uris: ['http://localhost:33418/callback'],
  token_endpoint_auth_method: 'none',
  registered_at: '2026-09-30T08:00:00Z',
  revoked_at: null,
  active_families: 3,
};
const REVOKED: OAuthClient = {
  ...CLIENT,
  client_id: 'oc_old',
  client_name: 'Old app',
  revoked_at: '2026-10-01T00:00:00Z',
  active_families: 0,
};

function renderPage() {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <MemoryRouter initialEntries={['/settings/admin/clients']}>
        <AdminClientsPage />
      </MemoryRouter>
    </Wrapper>,
  );
  return fast();
}

describe('AdminClientsPage', () => {
  beforeEach(() => {
    tokens.listClients.mockReset().mockResolvedValue([CLIENT, REVOKED]);
    tokens.revokeClient.mockReset().mockResolvedValue(undefined);
  });

  it('lists clients with their redirect host, live sign-ins and status', async () => {
    renderPage();
    const table = await screen.findByRole('table', { name: 'OAuth clients' });
    const [, live, old] = within(table).getAllByRole('row');
    expect(live).toHaveTextContent('Claude Code');
    expect(live).toHaveTextContent('localhost');
    expect(live).toHaveTextContent('3');
    expect(old).toHaveTextContent('revoked');
    expect(within(old!).queryByRole('button')).not.toBeInTheDocument();
  });

  it('revoke is reviewed first and names what stops working', async () => {
    const user = renderPage();
    await user.click(await screen.findByRole('button', { name: 'Revoke Claude Code' }));
    const card = screen.getByRole('region', { name: 'Revoke Claude Code' });
    expect(card).toHaveTextContent('client.revoked');
    expect(card).toHaveTextContent('3 connected sign-ins stop working');
    expect(tokens.revokeClient).not.toHaveBeenCalled();
    await user.click(within(card).getByRole('button', { name: 'Revoke client' }));
    await waitFor(() => expect(tokens.revokeClient).toHaveBeenCalledWith('oc_8f3a1c'));
  });

  it('no clients: an empty state', async () => {
    tokens.listClients.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText('No clients registered')).toBeInTheDocument();
  });

  it('a failed load is an error with Retry', async () => {
    tokens.listClients.mockRejectedValue(new Error('offline'));
    renderPage();
    expect(await screen.findByText("Couldn't load clients")).toBeInTheDocument();
  });
});
