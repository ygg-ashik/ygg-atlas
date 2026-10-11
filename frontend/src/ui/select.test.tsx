// src/ui/select.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Select } from './select';

describe('Select', () => {
  it('is a native combobox that reports changes', async () => {
    const onChange = vi.fn();
    render(
      <Select aria-label="Role" defaultValue="" onChange={(e) => onChange(e.target.value)}>
        <option value="">Role: any</option>
        <option value="admin">admin</option>
      </Select>,
    );
    const select = screen.getByRole('combobox', { name: 'Role' });
    expect(select).toHaveClass('appearance-none', 'bg-card');
    await userEvent.selectOptions(select, 'admin');
    expect(onChange).toHaveBeenCalledWith('admin');
  });
});
