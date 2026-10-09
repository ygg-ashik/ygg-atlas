// src/ui/tree-list.test.tsx
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { type TreeNode, TreeList } from './tree-list';

const GROUPS: TreeNode[] = [
  {
    id: 'marketing',
    label: 'marketing',
    count: '4 · 2',
    children: [
      { id: 'marketing-paid', label: 'marketing-paid', count: '2 · 1' },
      { id: 'growth', label: 'growth', count: '1 · 0', locked: true },
    ],
  },
  { id: 'leadership', label: 'leadership', count: '3 · 1' },
];

function Groups({ onSelect }: { onSelect?: (id: string) => void }) {
  const [sel, setSel] = useState('marketing');
  return (
    <TreeList
      label="Groups"
      nodes={GROUPS}
      selectedId={sel}
      onSelect={(id) => {
        setSel(id);
        onSelect?.(id);
      }}
    />
  );
}

const item = (name: string) => screen.getByRole('treeitem', { name });

describe('TreeList', () => {
  it('renders a tree with levels, selection, mono counts and locked nodes', () => {
    render(<Groups />);
    expect(screen.getByRole('tree', { name: 'Groups' })).toBeInTheDocument();
    const root = item('marketing');
    expect(root).toHaveAttribute('aria-level', '1');
    expect(root).toHaveAttribute('aria-expanded', 'true');
    expect(root).toHaveAttribute('aria-selected', 'true');
    expect(root).toHaveAttribute('tabindex', '0');
    expect(item('marketing-paid')).toHaveAttribute('aria-level', '2');
    expect(item('growth')).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText('4 · 2')).toHaveClass('font-mono');
  });

  it('selects on click but never selects a locked node', async () => {
    const onSelect = vi.fn();
    render(<Groups onSelect={onSelect} />);
    await userEvent.click(screen.getByText('growth'));
    expect(onSelect).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText('leadership'));
    expect(onSelect).toHaveBeenCalledWith('leadership');
    expect(item('leadership')).toHaveAttribute('aria-selected', 'true');
  });

  it('follows the tree keyboard pattern', async () => {
    const onSelect = vi.fn();
    render(<Groups onSelect={onSelect} />);
    act(() => item('marketing').focus());
    await userEvent.keyboard('{ArrowDown}');
    expect(item('marketing-paid')).toHaveFocus();
    await userEvent.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledWith('marketing-paid');
    await userEvent.keyboard('{ArrowLeft}');
    expect(item('marketing')).toHaveFocus();
    await userEvent.keyboard('{ArrowLeft}');
    expect(item('marketing')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('marketing-paid')).toBeNull();
    await userEvent.keyboard('{ArrowDown}');
    expect(item('leadership')).toHaveFocus();
  });

  it('outline variant is read-only with guide lines and trailing slots', async () => {
    const onSelect = vi.fn();
    render(
      <TreeList
        label="Catalog"
        variant="outline"
        onSelect={onSelect}
        nodes={[
          {
            id: 'demo',
            label: 'demo',
            detail: 'Commerce',
            children: [{ id: 'demo/order', label: 'order', trailing: <span>allow</span> }],
          },
        ]}
      />,
    );
    const root = item('demo Commerce');
    expect(root).not.toHaveAttribute('aria-selected');
    expect(root.querySelector('[role="group"]')).toHaveClass('border-l');
    expect(screen.getByText('allow')).toBeInTheDocument();
    await userEvent.click(screen.getByText('order'));
    expect(onSelect).not.toHaveBeenCalled();
  });
});
