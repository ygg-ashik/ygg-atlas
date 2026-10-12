// src/features/layout/account-menu.test.tsx
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { location, renderShell, USER } from './test-shell';

// The open menu hides the rest of the page from assistive tech; the chip stays queryable.
const chip = () =>
  within(screen.getByRole('complementary', { hidden: true })).getByRole('button', {
    name: 'Account menu',
    hidden: true,
  });

async function openMenu() {
  await userEvent.click(chip());
  return screen.findByRole('menu');
}

/** Pretend the viewport is a phone (< 600px). */
function asPhone() {
  vi.stubGlobal(
    'matchMedia',
    (query: string) =>
      ({
        matches: query === '(max-width: 599px)',
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.removeItem('ygg-atlas-theme');
});

describe('Account menu', () => {
  it('the chip shows name, email and role, and no dot without approvals', () => {
    renderShell('/ask');
    expect(chip()).toHaveTextContent('Sara Mansour');
    expect(chip()).toHaveTextContent('sara@yougotagift.com');
    expect(chip()).toHaveTextContent('admin');
    expect(within(chip()).queryByRole('img')).not.toBeInTheDocument();
  });

  it('a viewer gets header, Settings with ⌘, theme and sign out, but no Admin', async () => {
    renderShell('/ask', { user: { ...USER, role: 'viewer' } });
    const menu = await openMenu();
    expect(within(menu).getByText('sara@yougotagift.com')).toBeInTheDocument();
    expect(within(menu).getByRole('menuitem', { name: /Settings/ })).toHaveAttribute(
      'href',
      '/settings',
    );
    expect(within(menu).getByRole('menuitem', { name: /Settings/ })).toHaveTextContent('⌘,');
    expect(within(menu).queryByRole('menuitem', { name: /Admin/ })).not.toBeInTheDocument();
    expect(within(menu).getByRole('group', { name: 'Theme' })).toBeInTheDocument();
    expect(within(menu).getByRole('menuitem', { name: /Sign out/ })).toBeInTheDocument();
  });

  it('a manager or admin gets Admin with the pending count, and the chip a dot', async () => {
    renderShell('/ask', { admin: { to: '/settings/admin/requests', pendingApprovals: 3 } });
    expect(within(chip()).getByRole('img', { name: '3 pending approvals' })).toBeInTheDocument();
    const menu = await openMenu();
    const admin = within(menu).getByRole('menuitem', { name: /Admin/ });
    expect(admin).toHaveAttribute('href', '/settings/admin/requests');
    expect(admin).toHaveTextContent('3 pending approvals');
  });

  it('Admin without anything pending carries no badge', async () => {
    renderShell('/ask', { admin: { to: '/settings/admin/users', pendingApprovals: 0 } });
    const menu = await openMenu();
    expect(within(menu).getByRole('menuitem', { name: 'Admin' })).toHaveAttribute(
      'href',
      '/settings/admin/users',
    );
    expect(within(chip()).queryByRole('img')).not.toBeInTheDocument();
  });

  it('Settings opens the settings page', async () => {
    renderShell('/ask');
    const menu = await openMenu();
    await userEvent.click(within(menu).getByRole('menuitem', { name: /Settings/ }));
    expect(location.current).toBe('/settings');
  });

  it('switches the theme in place and keeps the menu open', async () => {
    renderShell('/ask');
    const menu = await openMenu();
    expect(within(menu).getByRole('menuitemradio', { name: 'Light' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    await userEvent.click(within(menu).getByRole('menuitemradio', { name: 'Dark' }));
    expect(document.documentElement).toHaveClass('dark');
    expect(screen.getByRole('menu')).toBeInTheDocument();
  });

  it('signs out', async () => {
    const onSignOut = vi.fn();
    renderShell('/ask', { onSignOut });
    const menu = await openMenu();
    await userEvent.click(within(menu).getByRole('menuitem', { name: /Sign out/ }));
    expect(onSignOut).toHaveBeenCalledOnce();
  });

  it('Escape closes the menu and returns focus to the chip', async () => {
    renderShell('/ask');
    await openMenu();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    expect(chip()).toHaveFocus();
  });

  it('renders no chip before the user is known', () => {
    renderShell('/ask', { user: null });
    expect(screen.queryByRole('button', { name: 'Account menu' })).not.toBeInTheDocument();
  });
});

describe('Below 600px', () => {
  it('the account menu is a bottom sheet with the same items', async () => {
    asPhone();
    renderShell('/ask', { admin: { to: '/settings/admin/requests', pendingApprovals: 2 } });
    await userEvent.click(chip());
    const sheet = await screen.findByRole('dialog', { name: 'Account' });
    expect(within(sheet).getByRole('link', { name: /Admin/ })).toHaveTextContent(
      '2 pending approvals',
    );
    expect(within(sheet).getByRole('radiogroup', { name: 'Theme' })).toBeInTheDocument();
    await userEvent.click(within(sheet).getByRole('link', { name: /Settings/ }));
    expect(location.current).toBe('/settings');
    expect(await screen.findByRole('heading', { level: 1, name: 'Settings' })).toBeVisible();
  });

  it('Settings drills down: list, page with a back chevron, back to the list', async () => {
    asPhone();
    renderShell('/settings/access');
    expect(screen.getByRole('main')).toHaveTextContent('page-content');
    await userEvent.click(screen.getByRole('button', { name: 'Back to Settings' }));
    const main = screen.getByRole('main');
    expect(within(main).getByRole('navigation', { name: 'Organization' })).toBeInTheDocument();
    expect(main).not.toHaveTextContent('page-content');
    await userEvent.click(within(main).getByRole('link', { name: /Users/ }));
    expect(location.current).toBe('/settings/admin/users');
    expect(screen.getByRole('main')).toHaveTextContent('page-content');
  });

  it('the list leads back to Atlas', async () => {
    asPhone();
    renderShell('/settings/access');
    await userEvent.click(screen.getByRole('button', { name: 'Back to Settings' }));
    await userEvent.click(screen.getByRole('button', { name: 'Atlas' }));
    expect(location.current).toBe('/');
  });
});
