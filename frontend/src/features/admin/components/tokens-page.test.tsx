import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type Availability } from '@/api/availability';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { type AdminTokenFilters, type RevokedCount, type Token } from '@/api/tokens';
import { accessView } from '@/test/access-view';
import { fast } from './test-fixtures';
import { AdminTokensPage } from './tokens-page';

const tokens = vi.hoisted(() => ({
  listAdminTokens: vi.fn<(f?: AdminTokenFilters) => Promise<Availability<Token[]>>>(),
  revokeAdminToken: vi.fn<(id: string) => Promise<void>>(),
  revokeAllUserTokens: vi.fn<(userId: string) => Promise<RevokedCount>>(),
}));
// The real token client is spread in; its axios instance pulls in the Firebase SDK.
vi.mock('@/lib/firebase', () => ({ auth: {}, googleProvider: {} }));
vi.mock('@/api/tokens', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  ...tokens,
}));
vi.mock('@/api/hooks/use-my-access', () => ({
  useMyAccess: () => accessView({ role: 'admin', capabilities: ['chat:use', 'admin:tokens'] }),
}));

function token(id: string, userId: string, overrides: Partial<Token> = {}): Token {
  return {
    id,
    kind: 'pat',
    name: `Token ${id}`,
    prefix: `atl_pat_${id}`,
    user_id: userId,
    client_id: null,
    created_at: '2026-10-01T08:00:00Z',
    expires_at: '2026-12-30T08:00:00Z',
    last_used_at: '2026-10-09T07:55:00Z',
    revoked_at: null,
    revoked_reason: null,
    ...overrides,
  };
}

const KARIM = 'u-karim';
const RANIA = 'u-rania';

function renderPage() {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <MemoryRouter initialEntries={['/admin/tokens']}>
        <AdminTokensPage />
      </MemoryRouter>
    </Wrapper>,
  );
  return fast();
}

describe('AdminTokensPage', () => {
  beforeEach(() => {
    tokens.listAdminTokens.mockReset().mockResolvedValue({
      available: true,
      data: [
        token('77c1', KARIM),
        token('e0b3', KARIM),
        token('3f9a', RANIA),
        token('dead', RANIA, { revoked_at: '2026-10-02T00:00:00Z' }),
      ],
    });
    tokens.revokeAdminToken.mockReset().mockResolvedValue(undefined);
    tokens.revokeAllUserTokens.mockReset().mockResolvedValue({ revoked: 2 });
  });

  it('groups live tokens by user', async () => {
    renderPage();
    const karim = await screen.findByRole('table', { name: `Tokens of ${KARIM}` });
    expect(within(karim).getAllByRole('row')).toHaveLength(3);
    const rania = screen.getByRole('table', { name: `Tokens of ${RANIA}` });
    expect(within(rania).getAllByRole('row')).toHaveLength(2);
    expect(screen.queryByText('atl_pat_dead…')).not.toBeInTheDocument();
  });

  it('revoke all for one user is reviewed first and lists exactly their tokens', async () => {
    const user = renderPage();
    await user.click(await screen.findByRole('button', { name: `Revoke all tokens of ${KARIM}` }));
    const card = screen.getByRole('region', { name: `Revoke all tokens · ${KARIM}` });
    expect(card).toHaveTextContent('token.revoke_all');
    expect(card).toHaveTextContent('atl_pat_77c1…');
    expect(card).toHaveTextContent('atl_pat_e0b3…');
    expect(card).not.toHaveTextContent('atl_pat_3f9a');
    expect(tokens.revokeAllUserTokens).not.toHaveBeenCalled();
    await user.click(within(card).getByRole('button', { name: 'Revoke 2 tokens' }));
    await waitFor(() => expect(tokens.revokeAllUserTokens).toHaveBeenCalledWith(KARIM));
  });

  it('revoking one token is reviewed first', async () => {
    const user = renderPage();
    await user.click(await screen.findByRole('button', { name: 'Revoke Token 3f9a' }));
    const card = screen.getByRole('region', { name: 'Revoke token' });
    expect(card).toHaveTextContent('token.revoke');
    await user.click(within(card).getByRole('button', { name: 'Revoke token' }));
    await waitFor(() => expect(tokens.revokeAdminToken).toHaveBeenCalledWith('3f9a'));
  });

  it('the kind filter is sent to the API', async () => {
    const user = renderPage();
    await screen.findByRole('table', { name: `Tokens of ${KARIM}` });
    await user.click(screen.getByRole('radio', { name: 'Service' }));
    await waitFor(() =>
      expect(tokens.listAdminTokens).toHaveBeenLastCalledWith({ kind: 'service' }),
    );
  });

  it('before phase 4 ships: "Not available yet"', async () => {
    tokens.listAdminTokens.mockResolvedValue({ available: false, reason: 'missing' });
    renderPage();
    expect(await screen.findByText('Not available yet')).toBeInTheDocument();
  });

  it('no live tokens: an empty state', async () => {
    tokens.listAdminTokens.mockResolvedValue({ available: true, data: [] });
    renderPage();
    expect(await screen.findByText('No live tokens')).toBeInTheDocument();
  });
});
