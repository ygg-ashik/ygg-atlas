// src/ui/segmented-control.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { SegmentedControl, tabPanelId } from './segmented-control';

type Tab = 'pending' | 'decided' | 'mine';
function Tabs({ kind }: { kind?: 'tabs' | 'radio' }) {
  const [v, setV] = useState<Tab>('pending');
  return (
    <>
      <SegmentedControl
        label="Requests"
        kind={kind}
        idBase="rq"
        value={v}
        onChange={setV}
        options={[
          { value: 'pending', label: 'Pending', count: 3 },
          { value: 'decided', label: 'Decided' },
          { value: 'mine', label: 'Mine', disabled: true },
        ]}
      />
      <output>{v}</output>
    </>
  );
}

describe('SegmentedControl', () => {
  it('renders a tablist with one selected, tabbable tab and its panel link', () => {
    render(<Tabs />);
    expect(screen.getByRole('tablist', { name: 'Requests' })).toBeInTheDocument();
    const pending = screen.getByRole('tab', { name: 'Pending 3' });
    expect(pending).toHaveAttribute('aria-selected', 'true');
    expect(pending).toHaveAttribute('tabindex', '0');
    expect(pending).toHaveAttribute('aria-controls', tabPanelId('rq', 'pending'));
    expect(screen.getByRole('tab', { name: 'Decided' })).toHaveAttribute('tabindex', '-1');
  });

  it('arrow keys move focus and select, skipping disabled segments', async () => {
    render(<Tabs />);
    screen.getByRole('tab', { name: 'Pending 3' }).focus();
    await userEvent.keyboard('{ArrowRight}');
    const decided = screen.getByRole('tab', { name: 'Decided' });
    expect(decided).toHaveFocus();
    expect(screen.getByRole('status')).toHaveTextContent('decided');
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Pending 3' })).toHaveFocus();
  });

  it('kind pills are a radiogroup and select on click', async () => {
    render(<Tabs kind="radio" />);
    expect(screen.getByRole('radiogroup', { name: 'Requests' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: 'Decided' }));
    expect(screen.getByRole('radio', { name: 'Decided' })).toHaveAttribute('aria-checked', 'true');
  });
});
