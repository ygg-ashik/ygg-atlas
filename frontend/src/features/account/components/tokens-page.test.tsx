import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type MyAccessView } from '@/api/hooks/use-my-access';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { type AuthMethods, type Token } from '@/api/tokens';
import { PERSONAS } from '@/test/access-view';
import { TokensPage } from './tokens-page';

const tokens = vi.hoisted(() => ({
  fetchAuthMethods: vi.fn<() => Promise<AuthMethods>>(),
  listMyTokens: vi.fn<() => Promise<Token[]>>(),
  revokeMyToken: vi.fn<(id: string) => Promise<void>>(),
  listConnectedApps: vi.fn(() => Promise.resolve([])),
}));
// The real token client is spread in; its axios instance pulls in the Firebase SDK.
vi.mock('@/lib/firebase', () => ({ auth: {}, googleProvider: {} }));
vi.mock('@/api/tokens', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ...tokens,
}));
const access = vi.hoisted(() => ({ view: null as MyAccessView | null }));
vi.mock('@/api/hooks/use-my-access', () => ({ useMyAccess: () => access.view }));

const METHODS: AuthMethods = {
  available: true,
  pat: { enabled: true, default_days: 90, max_days: 365 },
  oauth: { enabled: true, hosted_connectors: true },
};

const TOKEN: Token = {
  id: 't1',
  kind: 'pat',
  name: 'Claude Code · laptop',
  prefix: 'atl_pat_3f9a',
  user_id: 'u1',
  client_id: null,
  created_at: '2026-09-30T08:00:00Z',
  expires_at: '2026-12-29T08:00:00Z',
  last_used_at: null,
  revoked_at: null,
  revoked_reason: null,
};

function renderPage() {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <MemoryRouter initialEntries={['/account/tokens']}>
        <TokensPage />
      </MemoryRouter>
    </Wrapper>,
  );
  return userEvent.setup({ delay: null });
}

describe('TokensPage', () => {
  beforeEach(() => {
    access.view = PERSONAS.manager; // holds tokens:create
    tokens.fetchAuthMethods.mockReset().mockResolvedValue(METHODS);
    tokens.listMyTokens.mockReset().mockResolvedValue([TOKEN]);
    tokens.revokeMyToken.mockReset().mockResolvedValue(undefined);
  });

  it('lists live tokens with name, prefix, created, expires and last used', async () => {
    renderPage();
    const table = await screen.findByRole('table', { name: 'Personal access tokens' });
    const row = within(table).getAllByRole('row')[1]!;
    expect(row).toHaveTextContent('Claude Code · laptop');
    expect(row).toHaveTextContent('atl_pat_3f9a…');
    expect(row).toHaveTextContent('2026-09-30');
    expect(row).toHaveTextContent('2026-12-29');
    expect(row).toHaveTextContent('never');
    expect(screen.getByRole('button', { name: '＋ New token' })).toBeInTheDocument();
  });

  it('revoking your own token goes through a review card', async () => {
    const user = renderPage();
    await user.click(await screen.findByRole('button', { name: 'Revoke Claude Code · laptop' }));
    const card = screen.getByRole('region', { name: 'Revoke token' });
    expect(card).toHaveTextContent('atl_pat_3f9a…');
    expect(tokens.revokeMyToken).not.toHaveBeenCalled();
    await user.click(within(card).getByRole('button', { name: 'Revoke token' }));
    await waitFor(() => expect(tokens.revokeMyToken).toHaveBeenCalledWith('t1'));
  });

  it('can create: an empty list offers the first token', async () => {
    tokens.listMyTokens.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText('No tokens yet')).toBeInTheDocument();
  });

  it('without tokens:create and no tokens: the explanation, no New token', async () => {
    access.view = PERSONAS.viewer;
    tokens.listMyTokens.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/Personal tokens need/)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /New token/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Request analyst' })).toHaveAttribute(
      'href',
      '/account/requests/new?kind=role',
    );
  });

  it('without tokens:create but with old tokens: they can still be revoked', async () => {
    access.view = PERSONAS.viewer;
    renderPage();
    expect(
      await screen.findByRole('button', { name: 'Revoke Claude Code · laptop' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /New token/ })).not.toBeInTheDocument();
  });

  it('personal tokens turned off by the deployment: a notice and no New token', async () => {
    tokens.listMyTokens.mockResolvedValue([]);
    tokens.fetchAuthMethods.mockResolvedValue({
      available: true,
      pat: { enabled: false, default_days: 90, max_days: 365 },
      oauth: { enabled: false, hosted_connectors: false },
    });
    renderPage();
    expect(await screen.findAllByText('Not enabled for this deployment')).toHaveLength(2);
    expect(screen.queryByText('Not available yet')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /New token/ })).not.toBeInTheDocument();
  });

  it('a failed token load is an error with Retry and no New token', async () => {
    tokens.listMyTokens.mockRejectedValue(new Error('offline'));
    renderPage();
    expect(await screen.findByText("Couldn't load your tokens")).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /New token/ })).not.toBeInTheDocument();
  });
});
