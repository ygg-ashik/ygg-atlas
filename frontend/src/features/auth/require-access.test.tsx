import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type MyAccessView } from '@/api/hooks/use-my-access';
import { allows, type AccessRule } from './access-rule';
import { accessView, PERSONAS } from '@/test/access-view';
import { RequireAccess } from './require-access';

let view: MyAccessView = PERSONAS.admin;
vi.mock('@/api/hooks/use-my-access', () => ({ useMyAccess: () => view }));
let fetching = 0;
vi.mock('@tanstack/react-query', () => ({ useIsFetching: () => fetching }));

const USERS: AccessRule = { anyOf: ['admin:users'], need: 'admin:users' };
const REQUESTS: AccessRule = {
  anyOf: ['admin:users', 'admin:groups'],
  managers: true,
  need: 'admin:users',
};

function renderAt(rule: AccessRule, path = '/settings/admin/users') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="*"
          element={
            <RequireAccess rule={rule} title="Users">
              <p>secret admin page</p>
            </RequireAccess>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

const deniedPage = (cap: string) =>
  screen.queryByRole('region', { name: `This area needs ${cap}` });

describe('allows', () => {
  it('is false for every rule until access has loaded', () => {
    expect(allows(accessView({}, 'loading'), { anyOf: [], need: 'chat:use' })).toBe(false);
    expect(allows(accessView({}, 'unavailable'), { anyOf: [], need: 'chat:use' })).toBe(false);
  });

  it('opens an empty rule to any signed-in user whose access loaded', () => {
    expect(allows(PERSONAS.newViewer, { anyOf: [], need: 'chat:use' })).toBe(true);
  });

  it('opens on any one of the listed capabilities', () => {
    const groupsOnly = accessView({ capabilities: ['admin:groups'] });
    expect(allows(groupsOnly, REQUESTS)).toBe(true);
    expect(allows(groupsOnly, USERS)).toBe(false);
  });

  it('lets group managers through only where the rule says so', () => {
    expect(allows(PERSONAS.manager, REQUESTS)).toBe(true);
    expect(allows(PERSONAS.manager, USERS)).toBe(false);
  });
});

describe('RequireAccess', () => {
  beforeEach(() => {
    view = PERSONAS.admin;
    fetching = 0;
  });

  it('shows a busy skeleton while access loads, never the page or the guard', () => {
    view = accessView({}, 'loading');
    renderAt(USERS);
    expect(screen.getByRole('status')).toHaveTextContent('Loading');
    expect(screen.queryByText('secret admin page')).not.toBeInTheDocument();
    expect(deniedPage('admin:users')).not.toBeInTheDocument();
  });

  it('renders the denied page in place when the capability is missing', () => {
    view = PERSONAS.viewer;
    renderAt(USERS);
    const page = deniedPage('admin:users');
    expect(page).toHaveTextContent('Your role (viewer)');
    expect(page).toHaveTextContent('/settings/admin/users stays closed');
    expect(screen.queryByText('secret admin page')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Go to My access' })).toHaveAttribute(
      'href',
      '/settings/access',
    );
    expect(screen.getByRole('link', { name: 'Request access' })).toHaveAttribute(
      'href',
      '/settings/requests/new?kind=role',
    );
  });

  it('labels the toolbar with the title and the mono route', () => {
    view = PERSONAS.viewer;
    renderAt(USERS, '/settings/admin/users/u-9');
    expect(screen.getByRole('heading', { level: 1, name: 'Users' })).toBeInTheDocument();
    expect(document.querySelector('[data-route-label]')).toHaveTextContent(
      '/settings/admin/users/u-9',
    );
  });

  it('fails closed to the denied page when access is unavailable, with a retry', async () => {
    const refetch = vi.fn();
    view = { ...accessView({}, 'unavailable'), refetch };
    renderAt(USERS);
    expect(deniedPage('admin:users')).toHaveTextContent('Your role (unconfirmed)');
    expect(screen.queryByText('secret admin page')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it('morphs Retry to Loading… while the access answer is refetching', () => {
    fetching = 1;
    view = accessView({}, 'unavailable');
    renderAt(USERS);
    expect(screen.getByRole('button', { name: 'Loading' })).toBeDisabled();
    expect(deniedPage('admin:users')).toBeInTheDocument();
  });

  it('renders the children when the viewer holds the capability', () => {
    renderAt(USERS);
    expect(screen.getByText('secret admin page')).toBeInTheDocument();
    expect(deniedPage('admin:users')).not.toBeInTheDocument();
  });

  it('accepts any one capability of the set, or manager standing', () => {
    view = accessView({ capabilities: ['admin:groups'] });
    renderAt(REQUESTS, '/settings/admin/requests');
    expect(screen.getByText('secret admin page')).toBeInTheDocument();
  });

  it('lets a manager in where managers count', () => {
    view = PERSONAS.manager;
    renderAt(REQUESTS, '/settings/admin/requests');
    expect(screen.getByText('secret admin page')).toBeInTheDocument();
  });

  it('denies a manager where only the capability counts', () => {
    view = PERSONAS.manager;
    renderAt({ anyOf: ['admin:audit'], need: 'admin:audit' }, '/settings/admin/audit');
    expect(deniedPage('admin:audit')).toHaveTextContent('Your role (analyst)');
  });
});
