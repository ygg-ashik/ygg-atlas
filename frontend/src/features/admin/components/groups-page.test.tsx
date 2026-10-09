import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type MyAccessView } from '@/api/hooks/use-my-access';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { apiMock } from '@/api/test-api-mock';
import { accessView, PERSONAS } from '@/test/access-view';
import { diffLines, fast, grant, group, member } from './test-fixtures';
import { GroupDetailPage, GroupsPage } from './groups-page';

vi.mock('../hooks/use-debounced-value', () => ({ useDebouncedValue: <T,>(value: T) => value }));
vi.mock('@/api/axios-instance', () => apiMock);
const api = vi.hoisted(() => ({
  listGroups: vi.fn(),
  fetchGroupDetail: vi.fn(),
  listMembers: vi.fn(),
  listGrants: vi.fn(),
  deleteGroup: vi.fn(),
}));
vi.mock('@/api/admin-groups', () => ({ ...api, CANDIDATE_QUERY_MIN: 3, CANDIDATE_QUERY_MAX: 100 }));
let view: MyAccessView = PERSONAS.admin;
vi.mock('@/api/hooks/use-my-access', () => ({ useMyAccess: () => view }));

const GROUPS = [
  group('g-m', 'marketing'),
  group('g-mp', 'marketing-paid', 'g-m'),
  group('g-r', 'risk-ops'),
];

function RouteProbe() {
  return <span data-testid="route">{useLocation().pathname}</span>;
}

function renderAt(path: string) {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <MemoryRouter initialEntries={[path]}>
        <RouteProbe />
        <Routes>
          <Route path="/admin/groups" element={<GroupsPage />} />
          <Route path="/admin/groups/:id" element={<GroupDetailPage />} />
        </Routes>
      </MemoryRouter>
    </Wrapper>,
  );
}

describe('Groups', () => {
  beforeEach(() => {
    view = PERSONAS.admin;
    Object.values(api).forEach((fn) => fn.mockReset());
    api.listGroups.mockResolvedValue(GROUPS);
    api.fetchGroupDetail.mockImplementation((id: string) => {
      const g = GROUPS.find((x) => x.id === id) ?? GROUPS[0];
      const empty = id === 'g-r';
      return Promise.resolve({
        ...g,
        member_count: empty ? 0 : 2,
        grant_count: empty ? 0 : 1,
        path: [g?.name],
      });
    });
    api.listMembers.mockResolvedValue([member('omar')]);
    api.listGrants.mockResolvedValue([grant('4c2e91')]);
  });

  it('an admin sees the tree, members and grants of the first group', async () => {
    renderAt('/admin/groups');
    const tree = await screen.findByRole('tree', { name: 'Groups' });
    expect(within(tree).getByRole('treeitem', { name: 'marketing-paid' })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { level: 2, name: 'marketing' })).toBeInTheDocument();
    expect(await screen.findByRole('list', { name: 'Grants of marketing' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '＋ New group' })).toBeInTheDocument();
  });

  it('deleting a group in use is refused with the backend sentence, without a request', async () => {
    renderAt('/admin/groups/g-m');
    await fast().click(await screen.findByRole('button', { name: 'Delete group' }));
    expect(screen.getByRole('alert')).toHaveTextContent(
      "Remove the group's subgroups, members and grants first.",
    );
    expect(api.deleteGroup).not.toHaveBeenCalled();
  });

  it('deleting an empty group is reviewed first', async () => {
    renderAt('/admin/groups/g-r');
    await fast().click(await screen.findByRole('button', { name: 'Delete group' }));
    const card = screen.getByRole('region', { name: 'Delete group' });
    expect(diffLines(card)[0]).toEqual(['context', 'group.delete  risk-ops']);
    api.deleteGroup.mockResolvedValue(undefined);
    api.listGroups.mockResolvedValue(GROUPS.filter((g) => g.id !== 'g-r'));
    await fast().click(within(card).getByRole('button', { name: 'Delete group' }));
    expect(api.deleteGroup).toHaveBeenCalledWith('g-r');
    await waitFor(() => expect(screen.getByTestId('route')).toHaveTextContent(/^\/admin\/groups$/));
  });

  it('a manager sees their managed subtree from GET /admin/groups, and no grant controls', async () => {
    view = accessView({
      ...PERSONAS.manager.access,
      groups: [{ id: 'g-m', name: 'marketing', standing: 'manager' }],
    });
    // The backend answers a manager with their subtree, real parent ids kept.
    api.listGroups.mockResolvedValue(GROUPS.filter((g) => g.id !== 'g-r'));
    renderAt('/admin/groups');
    expect(await screen.findByRole('heading', { level: 2, name: 'marketing' })).toBeInTheDocument();
    expect(api.listGroups).toHaveBeenCalled();
    const tree = screen.getByRole('tree', { name: 'Groups' });
    expect(within(tree).getByRole('treeitem', { name: 'marketing' })).toHaveAttribute(
      'aria-level',
      '1',
    );
    expect(within(tree).getByRole('treeitem', { name: 'marketing-paid' })).toHaveAttribute(
      'aria-level',
      '2',
    );
    expect(within(tree).queryByRole('treeitem', { name: 'risk-ops' })).not.toBeInTheDocument();
    expect(api.listGrants).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: '＋ New group' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '＋ Add grant' })).not.toBeInTheDocument();
    expect(screen.getByText(/Managing grants needs/)).toBeInTheDocument();
  });

  it('a manager whose groups fail to load sees the failure, not an empty tree', async () => {
    view = PERSONAS.manager;
    api.listGroups.mockRejectedValue(new Error('down'));
    renderAt('/admin/groups');
    expect(await screen.findByText("Couldn't load groups")).toBeInTheDocument();
    expect(screen.queryByText('No groups yet')).not.toBeInTheDocument();
  });

  it('without admin:groups or management nothing is listed', () => {
    view = PERSONAS.viewer;
    renderAt('/admin/groups');
    expect(api.listGroups).not.toHaveBeenCalled();
  });
});
