// src/ui/radio-list.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { RadioList } from './radio-list';

function Picker() {
  const [v, setV] = useState<string | null>(null);
  return (
    <RadioList
      label="Who can approve it"
      value={v}
      onChange={setV}
      options={[
        { value: 'viewer', title: 'viewer', description: 'current', disabled: true },
        { value: 'marketing', title: 'marketing', description: 'Paid and owned channels' },
        { value: 'direct', title: 'Direct grant for me only', detail: 'Decided by an admin' },
      ]}
    />
  );
}

describe('RadioList', () => {
  it('is a radiogroup whose first enabled row is the tab stop', () => {
    render(<Picker />);
    expect(screen.getByRole('radiogroup', { name: 'Who can approve it' })).toBeInTheDocument();
    const rows = screen.getAllByRole('radio');
    expect(rows[0]).toHaveAttribute('aria-disabled', 'true');
    expect(rows[1]).toHaveAttribute('tabindex', '0');
    expect(rows.every((r) => r.getAttribute('aria-checked') === 'false')).toBe(true);
  });

  it('selects on click and ignores disabled rows', async () => {
    render(<Picker />);
    const [disabled, marketing] = screen.getAllByRole('radio') as [HTMLElement, HTMLElement];
    await userEvent.click(disabled);
    expect(disabled).toHaveAttribute('aria-checked', 'false');
    await userEvent.click(marketing);
    expect(marketing).toHaveAttribute('aria-checked', 'true');
    expect(marketing).toHaveClass('bg-primary/10');
  });

  it('arrow keys move and select; Space selects', async () => {
    render(<Picker />);
    const rows = screen.getAllByRole('radio') as [HTMLElement, HTMLElement, HTMLElement];
    rows[1].focus();
    await userEvent.keyboard(' ');
    expect(rows[1]).toHaveAttribute('aria-checked', 'true');
    await userEvent.keyboard('{ArrowDown}');
    expect(rows[2]).toHaveFocus();
    expect(rows[2]).toHaveAttribute('aria-checked', 'true');
    await userEvent.keyboard('{ArrowDown}');
    expect(rows[1]).toHaveFocus();
  });
});
