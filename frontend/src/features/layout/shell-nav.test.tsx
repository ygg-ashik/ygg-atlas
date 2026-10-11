import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Inbox, LayoutDashboard, MessageCircle, ShieldCheck, Users } from 'lucide-react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ThemeProvider } from '@/lib/theme-provider';
import Shell from './shell';
import { type AccountMenuItem, type ShellUser } from './account-controls';
import { type NavItem } from './sidebar-content';

const nav: NavItem[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/ask', label: 'Ask Atlas', icon: MessageCircle },
];

const sectioned: NavItem[] = [
  ...nav,
  { to: '/account', label: 'My access', icon: ShieldCheck, section: 'Account', end: true },
  {
    to: '/account/requests',
    label: 'My requests',
    icon: Inbox,
    section: 'Account',
    badge: { count: 2, label: 'pending requests' },
  },
  { to: '/admin/users', label: 'Users', icon: Users, section: 'Admin' },
  {
    to: '/admin/requests',
    label: 'Access requests',
    icon: Inbox,
    section: 'Admin',
    badge: { count: 0, label: 'requests to decide' },
  },
];

const USER: ShellUser = {
  name: 'Sara Mansour',
  email: 'sara@yougotagift.com',
  avatar: '',
  role: 'admin',
};
const MENU: AccountMenuItem[] = [
  { to: '/account', label: 'My access', icon: ShieldCheck },
  { to: '/account/tokens', label: 'Tokens & apps', icon: Inbox },
];

function renderAt(
  path: string,
  items: NavItem[] = nav,
  user: ShellUser | null = null,
  onSignOut = () => {},
) {
  render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Shell user={user} onSignOut={onSignOut} nav={items} menuItems={MENU}>
          <p>page</p>
        </Shell>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

const sidebar = () => screen.getByRole('complementary');

describe('Shell nav', () => {
  it('marks the root Overview link active only on / itself', () => {
    renderAt('/ask');
    expect(screen.getByRole('link', { name: /Overview/ })).not.toHaveAttribute('aria-current');
    expect(screen.getByRole('link', { name: /Ask Atlas/ })).toHaveAttribute('aria-current', 'page');
  });

  it('marks Overview active on /', () => {
    renderAt('/');
    expect(screen.getByRole('link', { name: /Overview/ })).toHaveAttribute('aria-current', 'page');
  });

  it('groups sectioned items under labelled section headers', () => {
    renderAt('/ask', sectioned);
    const account = within(sidebar()).getByRole('group', { name: 'Account' });
    expect(
      within(account)
        .getAllByRole('link')
        .map((l) => l.getAttribute('href')),
    ).toEqual(['/account', '/account/requests']);
    const admin = within(sidebar()).getByRole('group', { name: 'Admin' });
    expect(within(admin).getByRole('link', { name: /Users/ })).toHaveAttribute(
      'href',
      '/admin/users',
    );
  });

  it('renders a count badge with its meaning, and none at zero', () => {
    renderAt('/ask', sectioned);
    expect(within(sidebar()).getByRole('link', { name: /My requests/ })).toHaveTextContent(
      '2 pending requests',
    );
    expect(within(sidebar()).getByRole('link', { name: /Access requests/ })).toHaveTextContent(
      /^Access requests$/,
    );
  });

  it('keeps My access active only on /account itself; nested routes light their own item', () => {
    renderAt('/account/requests/new', sectioned);
    expect(within(sidebar()).getByRole('link', { name: 'My access' })).not.toHaveAttribute(
      'aria-current',
    );
    expect(within(sidebar()).getByRole('link', { name: /My requests/ })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });

  it('lights a section item on its detail routes', () => {
    renderAt('/admin/users/u-9', sectioned);
    expect(within(sidebar()).getByRole('link', { name: /Users/ })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });
});

describe('Shell user chip and account menu', () => {
  it('shows the signed-in user with name, email and role', () => {
    renderAt('/ask', nav, USER);
    const chip = within(sidebar()).getByRole('button', { name: 'Account menu' });
    expect(chip).toHaveTextContent('Sara Mansour');
    expect(chip).toHaveTextContent('sara@yougotagift.com');
    expect(chip).toHaveTextContent('admin');
  });

  it('opens the account menu with the composed links, theme choices and sign out', async () => {
    const onSignOut = vi.fn();
    renderAt('/ask', nav, USER, onSignOut);
    await userEvent.click(within(sidebar()).getByRole('button', { name: 'Account menu' }));
    const menu = await screen.findByRole('menu');
    expect(within(menu).getByRole('menuitem', { name: /My access/ })).toHaveAttribute(
      'href',
      '/account',
    );
    expect(within(menu).getByRole('menuitem', { name: /Tokens & apps/ })).toHaveAttribute(
      'href',
      '/account/tokens',
    );
    expect(within(menu).getByRole('menuitem', { name: /Dark/ })).toBeInTheDocument();
    await userEvent.click(within(menu).getByRole('menuitem', { name: /Sign out/ }));
    expect(onSignOut).toHaveBeenCalledOnce();
  });

  it('switches the theme from the account menu', async () => {
    localStorage.removeItem('ygg-atlas-theme');
    renderAt('/ask', nav, USER);
    expect(document.documentElement).not.toHaveClass('dark');
    await userEvent.click(within(sidebar()).getByRole('button', { name: 'Account menu' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Dark/ }));
    expect(document.documentElement).toHaveClass('dark');
    localStorage.removeItem('ygg-atlas-theme');
  });

  it('renders no chip before the user is known', () => {
    renderAt('/ask');
    expect(screen.queryByRole('button', { name: 'Account menu' })).not.toBeInTheDocument();
  });
});
