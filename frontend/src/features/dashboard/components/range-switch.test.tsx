import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { RangeSwitch } from './range-switch';

describe('RangeSwitch', () => {
  it('is a radiogroup with the active range checked', async () => {
    const onChange = vi.fn();
    render(<RangeSwitch value={30} onChange={onChange} />);
    expect(screen.getByRole('radio', { name: '30D' })).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(screen.getByRole('radio', { name: '7D' }));
    expect(onChange).toHaveBeenCalledWith(7);
  });
});
