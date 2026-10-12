// Test-only harness for the layout feature (src/test: shared test support): the
// shell at a path, with a probe of the current location. Imported only by *.test.tsx.
import { render } from '@testing-library/react';
import { Inbox, Library, MessageCircle, Settings2, ShieldCheck, Users } from 'lucide-react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider } from '@/lib/theme-provider';
import {
  Shell,
  type AdminEntry,
  type NavItem,
  type NavSection,
  type ShellUser,
} from '@/features/layout';

export const NAV: NavItem[] = [
  { to: '/ask', label: 'Ask Atlas', icon: MessageCircle },
  { to: '/metrics', label: 'Metrics', icon: Library },
];

export const SETTINGS: NavSection[] = [
  {
    title: 'You',
    items: [
      { to: '/settings', label: 'General', icon: Settings2 },
      { to: '/settings/access', label: 'My access', icon: ShieldCheck },
    ],
  },
  {
    title: 'Organization',
    items: [
      { to: '/settings/admin/users', label: 'Users', icon: Users },
      {
        to: '/settings/admin/requests',
        label: 'Access requests',
        icon: Inbox,
        badge: { count: 3, label: 'requests to decide' },
      },
    ],
  },
];

export const USER: ShellUser = {
  name: 'Sara Mansour',
  email: 'sara@yougotagift.com',
  avatar: '',
  role: 'admin',
};

export const location = { current: '' };
function Where() {
  const l = useLocation();
  location.current = l.pathname;
  return null;
}

interface Options {
  user?: ShellUser | null;
  admin?: AdminEntry;
  settings?: NavSection[];
  onSignOut?: () => void;
}

export function renderShell(path: string, options: Options = {}) {
  const { user = USER, admin, settings = SETTINGS, onSignOut = () => {} } = options;
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="*"
            element={
              <>
                <Where />
                <Shell
                  user={user}
                  onSignOut={onSignOut}
                  nav={NAV}
                  settings={settings}
                  admin={admin}
                  threads={<p>threads-slot</p>}
                >
                  <p>page-content</p>
                  <input aria-label="page field" />
                </Shell>
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}
