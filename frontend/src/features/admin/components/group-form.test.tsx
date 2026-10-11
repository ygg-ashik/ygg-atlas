import { render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryWrapper } from '@/api/hooks/test-query-wrapper';
import { diffLines, fast, group } from './test-fixtures';
import { GroupForm } from './group-form';

const createGroup = vi.hoisted(() => vi.fn());
const updateGroup = vi.hoisted(() => vi.fn());
vi.mock('@/api/admin-groups', () => ({ createGroup, updateGroup }));

const GROUPS = [
  group('g-m', 'marketing'),
  group('g-mp', 'marketing-paid', 'g-m'),
  group('g-c', 'csm'),
];

function renderForm(props: Partial<Parameters<typeof GroupForm>[0]> = {}) {
  const onDone = vi.fn();
  const { wrapper: Wrapper } = createQueryWrapper();
  render(
    <Wrapper>
      <GroupForm groups={GROUPS} onDone={onDone} {...props} />
    </Wrapper>,
  );
  return onDone;
}

describe('GroupForm', () => {
  beforeEach(() => {
    createGroup.mockReset();
    updateGroup.mockReset();
  });

  it('creates a group under a parent and closes', async () => {
    createGroup.mockResolvedValue(group('g-new', 'paid-social', 'g-m'));
    const onDone = renderForm();
    await fast().type(screen.getByRole('textbox', { name: /Name/ }), 'paid-social');
    await fast().selectOptions(screen.getByRole('combobox', { name: /Parent/ }), 'g-m');
    await fast().click(screen.getByRole('button', { name: 'Create group' }));
    expect(createGroup).toHaveBeenCalledWith({
      name: 'paid-social',
      description: '',
      parent_id: 'g-m',
    });
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it('an edit is reviewed as group.update with only the changed fields, then closes', async () => {
    updateGroup.mockResolvedValue(group('g-mp', 'marketing-paid', 'g-c'));
    const onDone = renderForm({ group: GROUPS[1] });
    const about = screen.getByRole('textbox', { name: 'Description' });
    await fast().clear(about);
    await fast().type(about, 'Paid acquisition');
    await fast().selectOptions(screen.getByRole('combobox', { name: /Parent/ }), 'g-c');
    await fast().click(screen.getByRole('button', { name: 'Review change' }));
    const card = screen.getByRole('region', { name: 'Edit group · marketing-paid' });
    expect(diffLines(card)).toEqual([
      ['context', 'group.update  marketing-paid'],
      ['remove', 'description marketing-paid team'],
      ['add', 'description Paid acquisition'],
      ['remove', 'parent    marketing'],
      ['add', 'parent    csm'],
    ]);
    expect(updateGroup).not.toHaveBeenCalled();
    await fast().click(within(card).getByRole('button', { name: 'Apply' }));
    expect(updateGroup).toHaveBeenCalledWith('g-mp', {
      description: 'Paid acquisition',
      parent_id: 'g-c',
    });
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it('a group cannot move under itself or a subgroup', () => {
    renderForm({ group: GROUPS[0] });
    const parent = screen.getByRole('combobox', { name: /Parent/ });
    expect(
      within(parent).queryByRole('option', { name: 'marketing-paid' }),
    ).not.toBeInTheDocument();
    expect(within(parent).getByRole('option', { name: 'csm' })).toBeInTheDocument();
  });
});
