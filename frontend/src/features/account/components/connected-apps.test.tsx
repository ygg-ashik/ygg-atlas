import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type Availability } from '@/api/availability';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { type AuthMethods, type ConnectedApp } from '@/api/tokens';
import { ConnectedApps } from './connected-apps';

const tokens = vi.hoisted(() => ({
  fetchAuthMethods: vi.fn<() => Promise<AuthMethods>>(),
  listConnectedApps: vi.fn<() => Promise<Availability<ConnectedApp[]>>>(),
  revokeConnectedApp: vi.fn<(familyId: string) => Promise<void>>(),
}));
// The real token client is spread in; its axios instance pulls in the Firebase SDK.
vi.mock('@/lib/firebase', () => ({ auth: {}, googleProvider: {} }));
vi.mock('@/api/tokens', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ...tokens,
}));

const methods = (oauth: AuthMethods['oauth']): AuthMethods => ({
  available: true,
  pat: { enabled: true, default_days: 90, max_days: 365 },
  oauth,
});
const ENABLED = methods({ enabled: true, hosted_connectors: true });

const APP: ConnectedApp = {
  family_id: 'fam-1',
  client_id: 'oc_8f3a1c',
  client_name: 'Claude Code',
  redirect_host: 'localhost',
  created_at: '2026-09-30T08:00:00Z',
  last_used_at: '2026-10-09T09:40:00Z',
  expires_at: '2026-12-29T08:00:00Z',
};

function renderApps() {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <ConnectedApps />
    </Wrapper>,
  );
  return userEvent.setup({ delay: null });
}

describe('ConnectedApps', () => {
  beforeEach(() => {
    tokens.fetchAuthMethods.mockReset().mockResolvedValue(ENABLED);
    tokens.listConnectedApps.mockReset().mockResolvedValue({ available: true, data: [] });
    tokens.revokeConnectedApp.mockReset().mockResolvedValue(undefined);
  });

  it('oauth disabled: "Not enabled for this deployment", and no list is read', async () => {
    tokens.fetchAuthMethods.mockResolvedValue(
      methods({ enabled: false, hosted_connectors: false }),
    );
    renderApps();
    expect(await screen.findByText('Not enabled for this deployment')).toBeInTheDocument();
    expect(tokens.listConnectedApps).not.toHaveBeenCalled();
  });

  it('a deployment without the flag route reads as disabled', async () => {
    tokens.fetchAuthMethods.mockResolvedValue({
      available: false,
      pat: { enabled: false, default_days: 0, max_days: 0 },
      oauth: { enabled: false, hosted_connectors: false },
    });
    renderApps();
    expect(await screen.findByText('Not enabled for this deployment')).toBeInTheDocument();
  });

  it('enabled and empty: the empty state names claude.ai only with hosted connectors', async () => {
    renderApps();
    expect(await screen.findByText('No connected apps yet')).toBeInTheDocument();
    expect(screen.getByText(/claude\.ai/)).toBeInTheDocument();
  });

  it('enabled and empty without hosted connectors: no claude.ai copy', async () => {
    tokens.fetchAuthMethods.mockResolvedValue(methods({ enabled: true, hosted_connectors: false }));
    renderApps();
    expect(await screen.findByText('No connected apps yet')).toBeInTheDocument();
    expect(screen.queryByText(/claude\.ai/)).not.toBeInTheDocument();
  });

  it('enabled but the route is missing: "Not available yet"', async () => {
    tokens.listConnectedApps.mockResolvedValue({ available: false, reason: 'missing' });
    renderApps();
    expect(await screen.findByText('Not available yet')).toBeInTheDocument();
  });

  it('populated: Revoke opens a review card and only Apply revokes the family', async () => {
    tokens.listConnectedApps.mockResolvedValue({ available: true, data: [APP] });
    const user = renderApps();
    const list = await screen.findByRole('list', { name: 'Connected apps' });
    const row = within(list).getByRole('listitem');
    expect(row).toHaveTextContent('Claude Code');
    expect(row).toHaveTextContent('oc_8f3a1c');
    await user.click(within(row).getByRole('button', { name: 'Revoke Claude Code' }));
    const card = screen.getByRole('region', { name: 'Revoke Claude Code' });
    expect(card).toHaveTextContent('client.revoke');
    expect(card).toHaveTextContent('its refresh tokens stop working immediately');
    expect(tokens.revokeConnectedApp).not.toHaveBeenCalled();
    await user.click(within(card).getByRole('button', { name: 'Revoke app' }));
    await waitFor(() => expect(tokens.revokeConnectedApp).toHaveBeenCalledWith('fam-1'));
  });

  it('Dismiss closes the review card without revoking', async () => {
    tokens.listConnectedApps.mockResolvedValue({ available: true, data: [APP] });
    const user = renderApps();
    await user.click(await screen.findByRole('button', { name: 'Revoke Claude Code' }));
    await user.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByRole('region', { name: 'Revoke Claude Code' })).not.toBeInTheDocument();
    expect(tokens.revokeConnectedApp).not.toHaveBeenCalled();
  });
});
