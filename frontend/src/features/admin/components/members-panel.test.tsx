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
vi.mock('../hooks/use-debounced-value', () => ({ useDebouncedValue: <T,>(value: T) => value }));
vi.mock('@/api/admin-groups', () => ({ listMembers, putMember, removeMember }));
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
});
