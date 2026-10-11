// Shell navigation per persona: the admin section and both badges come from `/me/access`.
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { type MyAccessView } from '@/api/hooks/use-my-access';
import { accessView, PERSONAS } from '@/test/access-view';
import { Shell } from '@/features/layout';
import { ThemeProvider } from '@/lib/theme-provider';
import { ACCOUNT_MENU, buildNav } from './navigation';

// The auth barrel pulls in the Firebase SDK; nothing here signs in.
vi.mock('@/lib/firebase', () => ({ auth: {}, googleProvider: {} }));

function renderNav(view: MyAccessView) {
  render(
    <ThemeProvider>
      <MemoryRouter initialEntries={['/ask']}>
        <Shell user={null} onSignOut={() => {}} nav={buildNav(view)} menuItems={ACCOUNT_MENU}>
          <p>page</p>
        </Shell>
      </MemoryRouter>
    </ThemeProvider>,
  );
  return screen.getByRole('complementary');
}

const adminLinks = (side: HTMLElement) =>
  within(within(side).getByRole('group', { name: 'Admin' }))
    .getAllByRole('link')
    .map((l) => l.getAttribute('href'));

describe('Shell navigation per persona', () => {
  it('new viewer: Account section, no Admin section, no badges', () => {
    const side = renderNav(PERSONAS.newViewer);
    expect(within(side).getByRole('group', { name: 'Account' })).toBeInTheDocument();
    expect(within(side).queryByRole('group', { name: 'Admin' })).not.toBeInTheDocument();
    expect(within(side).queryByText(/pending request|to decide/)).not.toBeInTheDocument();
  });

  it('viewer with data: their own pending requests badge My requests', () => {
    const side = renderNav(PERSONAS.viewer);
    expect(within(side).queryByRole('group', { name: 'Admin' })).not.toBeInTheDocument();
    expect(within(side).getByRole('link', { name: /My requests/ })).toHaveTextContent(
      '2 pending requests',
    );
  });

  it('manager: Groups and Access requests only, badged with pending_approvals', () => {
    const side = renderNav(PERSONAS.manager);
    expect(adminLinks(side)).toEqual(['/admin/groups', '/admin/requests']);
    expect(within(side).getByRole('link', { name: /Access requests/ })).toHaveTextContent(
      '3 requests to decide',
    );
  });

  it('admin: every admin entry; both badges from their own counts', () => {
    const side = renderNav(PERSONAS.admin);
    expect(adminLinks(side)).toEqual([
      '/admin/users',
      '/admin/groups',
      '/admin/requests',
      '/admin/audit',
    ]);
    expect(within(side).getByRole('link', { name: /Access requests/ })).toHaveTextContent(
      '5 requests to decide',
    );
    expect(within(side).getByRole('link', { name: /My requests/ })).toHaveTextContent(
      '1 pending request',
    );
    expect(within(side).getByRole('link', { name: /My requests/ })).not.toHaveTextContent(
      '1 pending requests',
    );
  });

  it('admin:tokens only: the Admin section holds just Tokens', () => {
    const side = renderNav(accessView({ capabilities: ['chat:use', 'admin:tokens'] }));
    expect(adminLinks(side)).toEqual(['/admin/tokens']);
  });

  it('admin:clients only: the Admin section holds just OAuth clients', () => {
    const side = renderNav(accessView({ capabilities: ['chat:use', 'admin:clients'] }));
    expect(adminLinks(side)).toEqual(['/admin/clients']);
  });

  it('an admin capability outside the admin pages opens no section', () => {
    const side = renderNav(accessView({ capabilities: ['chat:use', 'mcp:use', 'tokens:create'] }));
    expect(within(side).queryByRole('group', { name: 'Admin' })).not.toBeInTheDocument();
  });

  it.each(['loading', 'unavailable'] as const)('%s access shows no admin section', (status) => {
    const side = renderNav(accessView({}, status));
    expect(within(side).queryByRole('group', { name: 'Admin' })).not.toBeInTheDocument();
    expect(within(side).getByRole('link', { name: 'My access' })).toBeInTheDocument();
  });
});
