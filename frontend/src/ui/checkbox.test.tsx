// src/ui/checkbox.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Checkbox } from './checkbox';

describe('Checkbox', () => {
  it('is a labelled native checkbox toggled by click and Space', async () => {
    const onChange = vi.fn();
    render(<Checkbox label="I understand this restricts 4 members" onChange={onChange} />);
    const box = screen.getByRole('checkbox', { name: 'I understand this restricts 4 members' });
    await userEvent.click(box);
    expect(box).toBeChecked();
    box.focus();
    await userEvent.keyboard(' ');
    expect(box).not.toBeChecked();
    expect(onChange).toHaveBeenCalledTimes(2);
  });
});
