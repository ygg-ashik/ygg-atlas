import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { httpError } from '@/api/test-support';
import { PERSONAS } from '@/test/access-view';
import { CATALOG, fast, user } from './test-fixtures';
import { UsersPage } from './users-page';

const listUsers = vi.hoisted(() => vi.fn());
vi.mock('../hooks/use-debounced-value', () => ({ useDebouncedValue: <T,>(value: T) => value }));
vi.mock('@/api/admin-users', () => ({ listUsers }));
vi.mock('@/api/access', () => ({ fetchCapabilityCatalog: () => Promise.resolve(CATALOG) }));
vi.mock('@/api/hooks/use-my-access', () => ({ useMyAccess: () => PERSONAS.admin }));

function renderPage() {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <MemoryRouter initialEntries={['/admin/users']}>
        <Routes>
          <Route path="/admin/users" element={<UsersPage />} />
          <Route path="/admin/users/:id" element={<p>detail page</p>} />
        </Routes>
      </MemoryRouter>
    </Wrapper>,
  );
}

const lastFilters = () => listUsers.mock.calls.at(-1)?.[0];

describe('UsersPage', () => {
  beforeEach(() => {
    listUsers.mockReset();
    listUsers.mockImplementation(({ cursor }: { cursor?: string }) =>
      Promise.resolve(
        cursor
          ? { items: [user('zara')], next_cursor: null }
          : { items: [user('omar'), user('u1', { role: 'admin' })], next_cursor: 'c1' },
      ),
    );
  });

  it('lists users with role and status pills and marks you', async () => {
    renderPage();
    const table = await screen.findByRole('table', { name: 'Users' });
    expect(within(table).getByText('omar@yougotagift.com')).toBeInTheDocument();
    expect(within(table).getByText('you')).toBeInTheDocument();
    expect(within(table).getAllByText('active')).toHaveLength(2);
  });

  it('search is sent to the API, not filtered in the browser', async () => {
    renderPage();
    await screen.findByRole('table', { name: 'Users' });
    await fast().type(screen.getByRole('searchbox', { name: 'Search name or email' }), 'sara');
    await waitFor(() => expect(lastFilters()?.filters).toEqual({ q: 'sara' }));
  });

  it('role, status and kind filters update the query', async () => {
    renderPage();
    await screen.findByRole('table', { name: 'Users' });
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Role' }), 'analyst');
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Status' }), 'disabled');
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Kind' }), 'service');
    await waitFor(() =>
      expect(lastFilters()?.filters).toEqual({
        role: 'analyst',
        status: 'disabled',
        kind: 'service',
      }),
    );
  });

  it('"Load more" follows the cursor and appends', async () => {
    renderPage();
    await fast().click(await screen.findByRole('button', { name: 'Load more' }));
    expect(await screen.findByText('zara@yougotagift.com')).toBeInTheDocument();
    expect(lastFilters()?.cursor).toBe('c1');
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('an empty match offers Clear filters', async () => {
    listUsers.mockResolvedValue({ items: [], next_cursor: null });
    renderPage();
    await fast().type(screen.getByRole('searchbox', { name: 'Search name or email' }), 'zainab');
    expect(await screen.findByText('No users match “zainab”')).toBeInTheDocument();
    await fast().click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(screen.getByRole('searchbox', { name: 'Search name or email' })).toHaveValue('');
  });

  it('a load failure is stated with Retry', async () => {
    listUsers.mockRejectedValue(httpError(503, { detail: 'The access check is unavailable.' }));
    renderPage();
    expect(await screen.findByText("Couldn't load users")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('a row opens the user', async () => {
    renderPage();
    await fast().click(await screen.findByRole('row', { name: 'Open Omar' }));
    expect(await screen.findByText('detail page')).toBeInTheDocument();
  });
});
