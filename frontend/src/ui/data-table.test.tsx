// src/ui/data-table.test.tsx
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { type DataColumn, DataTable } from './data-table';

interface U {
  id: string;
  email: string;
  groups: number;
}
const ROWS: U[] = [
  { id: 'u1', email: 'sara@yougotagift.com', groups: 3 },
  { id: 'u2', email: 'omar@yougotagift.com', groups: 1 },
];
const COLS: DataColumn<U>[] = [
  { key: 'email', header: 'Email', cell: (u) => u.email },
  { key: 'kind', header: 'Kind', cell: () => 'human', hideBelowWide: true },
  { key: 'groups', header: 'Groups', cell: (u) => u.groups, align: 'end' },
];

describe('DataTable', () => {
  it('renders a captioned table with tabular figures and right-aligned numbers', () => {
    render(<DataTable caption="Users" columns={COLS} rows={ROWS} rowKey={(u) => u.id} />);
    const table = screen.getByRole('table', { name: 'Users' });
    expect(table).toHaveClass('tabular-nums', 'max-[999px]:min-w-[760px]');
    expect(table.parentElement).toHaveClass('overflow-x-auto', 'bg-card', 'rounded-card');
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Email',
      'Kind',
      'Groups',
    ]);
    expect(screen.getByRole('columnheader', { name: 'Kind' })).toHaveClass('max-[1199px]:hidden');
    expect(screen.getByRole('cell', { name: '3' })).toHaveClass('text-right');
  });

  it('clickable rows open on click, Enter and Space', async () => {
    const onRowClick = vi.fn();
    render(
      <DataTable
        caption="Users"
        columns={COLS}
        rows={ROWS}
        rowKey={(u) => u.id}
        rowAction={{ label: (u) => `Open ${u.email}`, onActivate: onRowClick }}
      />,
    );
    const [, first, second] = screen.getAllByRole('row') as [HTMLElement, HTMLElement, HTMLElement];
    await userEvent.click(within(first).getByText('sara@yougotagift.com'));
    expect(onRowClick).toHaveBeenLastCalledWith(ROWS[0]);
    expect(second).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('row', { name: 'Open omar@yougotagift.com' })).toBe(second);
    second.focus();
    await userEvent.keyboard('{Enter}');
    expect(onRowClick).toHaveBeenLastCalledWith(ROWS[1]);
    await userEvent.keyboard(' ');
    expect(onRowClick).toHaveBeenCalledTimes(3);
  });

  it('expandable rows toggle a detail row through a disclosure button', async () => {
    function Audit() {
      const [open, setOpen] = useState<string | null>(null);
      return (
        <DataTable
          caption="Changes"
          columns={COLS}
          rows={ROWS}
          rowKey={(u) => u.id}
          expandedKey={open}
          onToggleExpand={(k) => setOpen((cur) => (cur === k ? null : k))}
          renderExpanded={(u) => <div>diff for {u.id}</div>}
        />
      );
    }
    render(<Audit />);
    const toggle = screen.getAllByRole('button', { name: 'Details' })[0] as HTMLElement;
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    toggle.focus();
    await userEvent.keyboard('{Enter}');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('diff for u1')).toBeInTheDocument();
    const detailId = toggle.getAttribute('aria-controls') ?? '';
    expect(detailId).toMatch(/.+-u1-detail$/);
    expect(detailId).not.toBe('u1-detail');
    expect(document.getElementById(detailId)).toHaveTextContent('diff for u1');
    await userEvent.click(screen.getByText('sara@yougotagift.com'));
    expect(screen.queryByText('diff for u1')).toBeNull();
  });
});
