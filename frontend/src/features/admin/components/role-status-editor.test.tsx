import { render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { httpError } from '@/api/test-support';
import { CATALOG, diffLines, fast, user } from './test-fixtures';
import { RoleStatusEditor } from './role-status-editor';

const updateUser = vi.hoisted(() => vi.fn());
vi.mock('@/api/admin-users', () => ({ updateUser }));
const actionToast = vi.hoisted(() => vi.fn());
vi.mock('@/ui', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  actionToast,
}));

const omar = user('omar', { role: 'viewer' });

function renderEditor(isSelf = false) {
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <RoleStatusEditor user={omar} isSelf={isSelf} roles={CATALOG.roles} />
    </Wrapper>,
  );
}

const card = () => screen.getByRole('region', { name: /Change role|Change status/ });
const diff = () => diffLines(card());

describe('RoleStatusEditor', () => {
  beforeEach(() => {
    updateUser.mockReset();
    actionToast.mockReset();
  });

  it('a role change opens a review card whose diff is the rbac_changes before → after', async () => {
    renderEditor();
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Role' }), 'analyst');
    expect(diff()).toEqual([
      ['context', 'user.role  omar@yougotagift.com'],
      ['remove', 'role      viewer'],
      ['add', 'role      analyst'],
      ['context', 'gains     mcp:use, tokens:create'],
    ]);
    expect(within(card()).getByText('user.role')).toBeInTheDocument();
    expect(updateUser).not.toHaveBeenCalled();
  });

  it('applies only on approval', async () => {
    updateUser.mockResolvedValue({ ...omar, role: 'analyst' });
    renderEditor();
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Role' }), 'analyst');
    await fast().click(within(card()).getByRole('button', { name: 'Apply role change' }));
    expect(updateUser).toHaveBeenCalledWith('omar', { role: 'analyst' });
    await waitFor(() => expect(card()).toHaveAttribute('data-status', 'applied'));
  });

  it('a status change is reviewed too', async () => {
    renderEditor();
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Status' }), 'disabled');
    expect(diff()).toContainEqual(['add', 'status    disabled']);
  });

  it('dismiss puts the select back', async () => {
    renderEditor();
    const role = screen.getByRole('combobox', { name: 'Role' });
    await fast().selectOptions(role, 'builder');
    await fast().click(within(card()).getByRole('button', { name: 'Dismiss' }));
    expect(role).toHaveValue('viewer');
    expect(screen.queryByRole('region', { name: /Change role/ })).not.toBeInTheDocument();
  });

  it('self-edit is disabled with the backend sentence', () => {
    renderEditor(true);
    expect(screen.getByRole('combobox', { name: 'Role' })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: 'Status' })).toBeDisabled();
    expect(
      screen.getByText("You can't change your own role or status. Ask another admin."),
    ).toBeInTheDocument();
  });

  it('a 409 shows the conflict and an action toast with Retry', async () => {
    updateUser.mockRejectedValueOnce(
      httpError(409, { detail: 'Access changed while this request was running; retry.' }),
    );
    updateUser.mockResolvedValueOnce({ ...omar, role: 'analyst' });
    renderEditor();
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Role' }), 'analyst');
    await fast().click(within(card()).getByRole('button', { name: 'Apply role change' }));
    await waitFor(() => expect(card()).toHaveAttribute('data-status', 'conflict'));
    expect(actionToast).toHaveBeenCalledWith(
      'Access changed while this request was running; retry.',
      expect.objectContaining({ actionLabel: 'Retry' }),
    );
    const { onAction } = actionToast.mock.calls[0]?.[1] as { onAction: () => void };
    onAction();
    await waitFor(() => expect(card()).toHaveAttribute('data-status', 'applied'));
    expect(updateUser).toHaveBeenCalledTimes(2);
  });

  it('a 403 keeps the card open with the backend sentence', async () => {
    updateUser.mockRejectedValue(
      httpError(403, { detail: "You can't assign a role with more access than your own." }),
    );
    renderEditor();
    await fast().selectOptions(screen.getByRole('combobox', { name: 'Role' }), 'admin');
    await fast().click(within(card()).getByRole('button', { name: 'Apply role change' }));
    expect(
      await within(card()).findByText("You can't assign a role with more access than your own."),
    ).toBeInTheDocument();
    expect(actionToast).not.toHaveBeenCalled();
  });
});
