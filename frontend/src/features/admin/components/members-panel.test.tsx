import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type MyAccessView } from '@/api/hooks/use-my-access';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { httpError } from '@/api/test-support';
import { PERSONAS } from '@/test/access-view';
import { diffLines, fast, member, user } from './test-fixtures';
import { MembersPanel } from './members-panel';

const listMembers = vi.hoisted(() => vi.fn());
const putMember = vi.hoisted(() => vi.fn());
const removeMember = vi.hoisted(() => vi.fn());
const listMemberCandidates = vi.hoisted(() => vi.fn());
vi.mock('../hooks/use-debounced-value', () => ({ useDebouncedValue: <T,>(value: T) => value }));
vi.mock('@/api/admin-groups', () => ({
  listMembers,
  putMember,
  removeMember,
  listMemberCandidates,
  CANDIDATE_QUERY_MIN: 3,
  CANDIDATE_QUERY_MAX: 100,
}));
const listUsers = vi.hoisted(() => vi.fn());
vi.mock('@/api/admin-users', () => ({ listUsers }));
let view: MyAccessView = PERSONAS.manager;
vi.mock('@/api/hooks/use-my-access', () => ({ useMyAccess: () => view }));

function renderPanel() {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <MemoryRouter>
        <MembersPanel groupId="g-m" groupName="marketing" />
      </MemoryRouter>
    </Wrapper>,
  );
}

const row = (name: string) => screen.getByRole('listitem', { name });

describe('MembersPanel', () => {
  beforeEach(() => {
    listMembers.mockReset();
    listMembers.mockResolvedValue([
      member('u1', 'manager'),
      member('omar'),
      member('yousef', 'manager'),
    ]);
    putMember.mockReset();
    removeMember.mockReset();
    listMemberCandidates.mockReset();
    listMemberCandidates.mockResolvedValue([
      { user_id: 'sara', display_name: 'Sara Mansour', email: 'sara@yougotagift.com' },
    ]);
    listUsers.mockReset();
    listUsers.mockResolvedValue({
      items: [user('sara', { display_name: 'Sara Mansour' })],
      next_cursor: null,
    });
  });

  describe('as a group manager (no admin:groups)', () => {
    beforeEach(() => {
      view = PERSONAS.manager;
    });

    it('can remove plain members only, never managers or themself', async () => {
      renderPanel();
      await screen.findByRole('list', { name: 'Members of marketing' });
      expect(within(row('Omar')).getByRole('button', { name: 'Remove Omar' })).toBeInTheDocument();
      expect(within(row('Yousef')).queryByRole('button')).not.toBeInTheDocument();
      expect(within(row('Yousef')).getByText('manager · admin only')).toBeInTheDocument();
      expect(
        within(row('U1')).getByText("Managers can't change their own membership"),
      ).toBeInTheDocument();
    });

    it('a removal goes through a review card first', async () => {
      removeMember.mockResolvedValue(undefined);
      renderPanel();
      await fast().click(await screen.findByRole('button', { name: 'Remove Omar' }));
      const card = screen.getByRole('region', { name: 'Remove member' });
      expect(diffLines(card)).toEqual([
        ['context', 'member.remove  marketing'],
        ['context', 'user      omar@yougotagift.com'],
        ['remove', 'standing  member'],
        ['add', 'standing  —'],
      ]);
      expect(removeMember).not.toHaveBeenCalled();
      await fast().click(within(card).getByRole('button', { name: 'Remove' }));
      expect(removeMember).toHaveBeenCalledWith('g-m', 'omar');
    });

    it('a refusal reads the backend sentence', async () => {
      removeMember.mockRejectedValue(
        httpError(403, { detail: 'This needs admin:groups. Ask an atlas admin.' }),
      );
      renderPanel();
      await fast().click(await screen.findByRole('button', { name: 'Remove Omar' }));
      await fast().click(
        within(screen.getByRole('region', { name: 'Remove member' })).getByRole('button', {
          name: 'Remove',
        }),
      );
      expect(
        await screen.findByText('This needs admin:groups. Ask an atlas admin.'),
      ).toBeInTheDocument();
    });

    it('adds a plain member through the candidate search (3+ characters)', async () => {
      putMember.mockResolvedValue(member('sara'));
      renderPanel();
      const search = await screen.findByRole('combobox', { name: 'Find a person' });
      await fast().type(search, 'sa');
      expect(await screen.findByText(/Type at least 3 characters/)).toBeInTheDocument();
      expect(listMemberCandidates).not.toHaveBeenCalled();
      await fast().type(search, 'r');
      await fast().click(await screen.findByRole('option', { name: /Sara Mansour/ }));
      expect(listMemberCandidates).toHaveBeenCalledWith('g-m', 'sar');
      expect(listUsers).not.toHaveBeenCalled();
      await fast().click(screen.getByRole('button', { name: 'Add member' }));
      const card = screen.getByRole('region', { name: 'Add member' });
      expect(diffLines(card).at(-1)).toEqual(['add', 'standing  member']);
      await fast().click(within(card).getByRole('button', { name: 'Add member' }));
      expect(putMember).toHaveBeenCalledWith('g-m', 'sara', 'member');
    });

    it('a 403 from the candidate search hides the picker with the sentence', async () => {
      listMemberCandidates.mockRejectedValue(
        httpError(403, { detail: 'Only managers of this group can add members.' }),
      );
      renderPanel();
      await fast().type(await screen.findByRole('combobox', { name: 'Find a person' }), 'sar');
      expect(
        await screen.findByText(/Only managers of this group can add members\./),
      ).toBeInTheDocument();
      expect(screen.queryByRole('combobox', { name: 'Find a person' })).not.toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Access requests' })).toBeInTheDocument();
    });

    it('cannot appoint managers: no standing choice', async () => {
      renderPanel();
      await screen.findByRole('list', { name: 'Members of marketing' });
      expect(screen.queryByRole('combobox', { name: 'Standing' })).not.toBeInTheDocument();
    });
  });

  describe('as an admin', () => {
    beforeEach(() => {
      view = PERSONAS.admin;
    });

    it('adds a manager through the picker and a review card', async () => {
      putMember.mockResolvedValue(member('sara', 'manager'));
      renderPanel();
      await fast().type(await screen.findByRole('combobox', { name: 'Find a person' }), 'sara');
      await fast().click(await screen.findByRole('option', { name: /Sara Mansour/ }));
      await fast().selectOptions(screen.getByRole('combobox', { name: 'Standing' }), 'manager');
      await fast().click(screen.getByRole('button', { name: 'Add member' }));
      const card = screen.getByRole('region', { name: 'Add member' });
      expect(diffLines(card)).toEqual([
        ['context', 'member.put  marketing'],
        ['context', 'user      sara@yougotagift.com'],
        ['remove', 'standing  —'],
        ['add', 'standing  manager'],
      ]);
      await fast().click(within(card).getByRole('button', { name: 'Add member' }));
      expect(putMember).toHaveBeenCalledWith('g-m', 'sara', 'manager');
      await waitFor(() => expect(card).toHaveAttribute('data-status', 'applied'));
      expect(listUsers).toHaveBeenCalledWith(expect.objectContaining({ filters: { q: 'sara' } }));
    });

    it('can remove a manager', async () => {
      renderPanel();
      await screen.findByRole('list', { name: 'Members of marketing' });
      expect(
        within(row('Yousef')).getByRole('button', { name: 'Remove Yousef' }),
      ).toBeInTheDocument();
    });
  });

  it('a viewer who is neither admin nor manager gets no picker', async () => {
    view = PERSONAS.viewer;
    renderPanel();
    await screen.findByRole('list', { name: 'Members of marketing' });
    expect(screen.queryByRole('combobox', { name: 'Find a person' })).not.toBeInTheDocument();
    expect(screen.getByText(/People join through their access requests/)).toBeInTheDocument();
  });
});
